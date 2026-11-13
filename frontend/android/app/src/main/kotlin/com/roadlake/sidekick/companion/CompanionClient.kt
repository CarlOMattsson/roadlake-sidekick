package com.roadlake.sidekick.companion

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Locale
import java.util.TimeZone

/** The server's answer to a request: its HTTP status and body text (JSON), for any status. */
class CompanionResponse(val status: Int, val body: String, val retryAfterSeconds: Int? = null)

/**
 * What `status()` tells the page. No token, no secret: whether paired, which host, and the rooms the server last said
 * the instance shows and the owner's time zone (null when it never did).
 */
class PairingStatus(
    val paired: Boolean,
    val serverHost: String?,
    val deviceLabel: String?,
    val enabledRooms: List<String>? = null,
    val ownerTimeZone: String? = null,
) {
    companion object {
        val UNPAIRED = PairingStatus(paired = false, serverHost = null, deviceLabel = null)
    }
}

/**
 * The native side of the companion contract, free of Android types so it is unit tested on the JVM.
 *
 * It owns the pairing and the bearer token. The page asks for a closed request shape; this class validates it
 * ([RequestPolicy]), adds the token and the server origin it was paired with, and returns the server's answer. A 401
 * from the server on an authenticated request means the credential is no longer valid: it is removed and
 * [onPairingLost] runs so the app shows the pairing form again.
 */
class CompanionClient(
    private val store: PairingStore,
    private val http: HttpTransport,
    private val allowLocalCleartext: Boolean,
    private val onPairingLost: () -> Unit = {},
    /** Runs in [unpair] while the credential still exists, before the device is revoked (the push subscription goes first). */
    private val onBeforeUnpair: () -> Unit = {},
    /** Epoch millis; the time of a pairing whose device the server did not date. */
    private val clock: () -> Long = System::currentTimeMillis,
    /** Work pinned to an earlier pairing generation is refused with `not_paired` ([PairingGeneration.pinned]). */
    private val generation: PairingGeneration = PairingGeneration(),
) {
    fun request(
        method: String?,
        path: String?,
        query: Map<String, List<String>>?,
        bodyJson: String?,
        idempotencyKey: String?,
    ): CompanionResponse {
        val checkedMethod = RequestPolicy.checkMethod(method, path)
        val checkedPath = RequestPolicy.checkPath(path)
        val queryString = RequestPolicy.encodeQuery(query)
        val body = RequestPolicy.checkBody(checkedMethod, bodyJson)
        val key = RequestPolicy.checkIdempotencyKey(idempotencyKey)
        if (key != null && checkedMethod != "POST") throw CompanionException("bad_request")

        return send(checkedMethod, checkedPath + queryString, body, key)
    }

    /**
     * Registers the push endpoint of this phone (`PUT /companion/v1/push/subscription`); a new one replaces the old. A
     * route of its own, not reachable from the page: `request` allows GET and POST, and PUT only for the license. The endpoint is never logged.
     */
    fun putPushSubscription(endpoint: String): CompanionResponse =
        send("PUT", PUSH_PATH, JSONObject().put("endpoint", endpoint).toString().toByteArray(Charsets.UTF_8), null)

    /** Removes this phone's push subscription (`DELETE /companion/v1/push/subscription`, 204). */
    fun deletePushSubscription(): CompanionResponse = send("DELETE", PUSH_PATH, null, null)

    /** The visible reminders waiting for this phone (`GET /companion/v1/reminders/pending`). Not reachable from the page. */
    fun pendingReminders(): CompanionResponse = send("GET", REMINDERS_PATH + "/pending", null, null)

    /** Tells the server these reminders were shown (`POST /companion/v1/reminders/ack`, 204), so it sends them no more. */
    fun ackReminders(ids: List<String>): CompanionResponse = send(
        "POST",
        REMINDERS_PATH + "/ack",
        JSONObject().put("ids", JSONArray(ids)).toString().toByteArray(Charsets.UTF_8),
        null,
    )

    /**
     * Asks for a new credential (`POST /companion/v1/device/renew`, no body, the current token). Only [TokenRenewal]
     * calls it: it decides when, and keeps the answer. A 401 ends the pairing as for any request. The new token is in the
     * answer and nowhere else; it is never logged.
     */
    fun renew(): CompanionResponse = send("POST", DEVICE_PATH + "/renew", null, null)

    /**
     * What the phone knows about its own device for the page. The stored record is the answer; when the server can be
     * reached (`GET /companion/v1/device`) it is refreshed first. No network, or any answer but 200, keeps the stored.
     */
    fun deviceStatus(): DeviceStatus {
        val before = store.load() ?: return DeviceStatus.UNPAIRED
        val answer = try {
            send("GET", DEVICE_PATH, null, null)
        } catch (_: CompanionException) {
            return DeviceStatus.of(before)
        }
        if (answer.status == 200) {
            val info = DeviceInfo.ofBody(answer.body)
            updateIfCurrent(before) { it.withDevice(info) }
        }
        val after = store.load() ?: return DeviceStatus.UNPAIRED
        return DeviceStatus.of(after)
    }

    /** `POST /companion/v1/push/test`, mapped to what the page needs to say (see [TestPushResult.of]). */
    fun sendTestPush(): TestPushResult {
        val answer = try {
            send("POST", PUSH_TEST_PATH, null, null)
        } catch (e: CompanionException) {
            return if (e.code == "not_paired") TestPushResult.UNPAIRED else TestPushResult.OFFLINE
        }
        return TestPushResult.of(answer)
    }

    /**
     * Writes a changed record of the pairing [used] unless that pairing has meanwhile ended or been replaced. A storage
     * failure is not the caller's concern (the dates are a convenience); false then.
     */
    internal fun updateIfCurrent(used: Pairing, change: (Pairing) -> Pairing): Boolean = PairingLock.atomically {
        val current = store.load()
        if (current == null || current.token != used.token) {
            false
        } else {
            try {
                store.update(change(current))
                true
            } catch (_: CompanionException) {
                false
            }
        }
    }

    private fun send(method: String, pathAndQuery: String, body: ByteArray?, key: String?): CompanionResponse {
        val pairing = store.load() ?: throw CompanionException("not_paired")
        generation.checkPinned() // after the load: a pairing loaded here that is newer than the work's is caught
        val server = ServerUrl.parse(pairing.serverOrigin, allowLocalCleartext)
        val headers = LinkedHashMap<String, String>()
        headers["Authorization"] = "Bearer ${pairing.token}"
        if (body != null) headers["Content-Type"] = "application/json"
        if (key != null) headers["Idempotency-Key"] = key

        val result = http.execute(HttpCall(method, server.origin + pathAndQuery, headers, body))
        if (result.status == 401) dropPairingIfCurrent(pairing)
        return CompanionResponse(result.status, result.body, result.retryAfterSeconds)
    }

    fun status(): PairingStatus {
        val pairing = store.load() ?: return PairingStatus.UNPAIRED
        val server = try {
            ServerUrl.parse(pairing.serverOrigin, allowLocalCleartext)
        } catch (_: CompanionException) {
            clearIfCurrent(pairing)
            return PairingStatus.UNPAIRED
        }
        return PairingStatus(
            paired = true,
            serverHost = server.host,
            deviceLabel = pairing.deviceLabel,
            enabledRooms = pairing.enabledRooms,
            ownerTimeZone = pairing.ownerTimeZone,
        )
    }

    /**
     * Exchanges the pairing secret for a device credential and keeps it. The device label is the operator's, set when
     * the pairing was issued; the exchange carries only the secret.
     */
    fun pair(serverUrl: String?, pairingSecret: String?): PairingStatus {
        if (store.load() != null) throw CompanionException("already_paired")
        val server = ServerUrl.parse(serverUrl ?: "", allowLocalCleartext)
        val secret = pairingSecret?.trim().orEmpty()
        if (!PAIRING_SECRET.matches(secret)) throw CompanionException("invalid_pairing_secret")
        // The old pairing's data must be gone before the code is spent on a pairing that could not be kept.
        if (!store.readyForPairing()) throw CompanionException("previous_data_not_removed")

        val body = JSONObject().put("pairing_secret", secret).toString().toByteArray(Charsets.UTF_8)
        val result = http.execute(
            HttpCall("POST", server.origin + PAIR_PATH, mapOf("Content-Type" to "application/json"), body),
        )
        if (result.status != 201) throw CompanionException(errorCodeOf(result))

        val token: String
        val device: DeviceInfo
        try {
            val json = JSONObject(result.body)
            token = json.getString("access_token")
            device = DeviceInfo.ofAnswer(json)
        } catch (_: JSONException) {
            throw CompanionException("bad_response")
        }
        if (!CredentialFormat.TOKEN.matches(token)) throw CompanionException("bad_response")

        try {
            // A pairing made while the exchange was in flight is not overwritten (the new device is revoked below).
            PairingLock.atomically {
                if (store.load() != null) throw CompanionException("already_paired")
                store.save(
                    Pairing(
                        server.origin,
                        token,
                        device.label,
                        device.createdAt ?: nowIso(),
                        device.expiresAt,
                        device.renewAfter,
                        device.enabledRooms,
                        device.ownerTimeZone,
                        device.pushEnabled,
                    ),
                )
            }
        } catch (e: CompanionException) {
            // The server created a device the phone cannot keep: revoke it so no unusable credential stays valid.
            revokeOnServer(server, token)
            throw e
        }
        return PairingStatus(
            paired = true,
            serverHost = server.host,
            deviceLabel = device.label,
            enabledRooms = device.enabledRooms,
            ownerTimeZone = device.ownerTimeZone,
        )
    }

    private fun nowIso(): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss'Z'", Locale.ROOT).apply { timeZone = TimeZone.getTimeZone("UTC") }.format(clock())

    /**
     * Removes this device on the server and everything stored here. The phone is always cleared; the result says whether
     * the server confirmed the revocation (so the page can tell the owner to have the server revoke the device when not).
     */
    fun unpair(): Boolean {
        val pairing = store.load() ?: return false
        try {
            runCatching { onBeforeUnpair() }
            val server = ServerUrl.parse(pairing.serverOrigin, allowLocalCleartext)
            return revokeOnServer(server, pairing.token)
        } catch (_: CompanionException) {
            return false
        } finally {
            // Clears the device we started unpairing, also under a credential renewed while the revocation was in flight.
            // A different pairing made meanwhile (after a 401 clear and a new pairing) is not ours to delete.
            clearIf { it.isSameDeviceAs(pairing) }
        }
    }

    private fun revokeOnServer(server: ServerUrl, token: String): Boolean = try {
        val result = http.execute(
            HttpCall("DELETE", server.origin + DEVICE_PATH, mapOf("Authorization" to "Bearer $token"), null),
        )
        // 204: revoked now. 401: the credential was already invalid, so there is nothing left to revoke.
        result.status == 204 || result.status == 401
    } catch (_: CompanionException) {
        false
    }

    /** A 401 clears the pairing it was sent with, not a newer pairing made while the request was in flight. */
    private fun dropPairingIfCurrent(used: Pairing) {
        if (clearIfCurrent(used)) onPairingLost()
    }

    /** Clears the stored pairing only if it is still the one [used]; true when it did. Check and clear are one step. */
    private fun clearIfCurrent(used: Pairing): Boolean = clearIf { it.token == used.token }

    /** Clears the stored pairing only if [matches] it; true when it did. Check and clear are one step. */
    private fun clearIf(matches: (Pairing) -> Boolean): Boolean = PairingLock.atomically {
        val stored = store.load()
        if (stored == null || !matches(stored)) {
            false
        } else {
            store.clear()
            true
        }
    }

    private fun errorCodeOf(result: HttpResult): String {
        val code = try {
            JSONObject(result.body).optString("code")
        } catch (_: JSONException) {
            ""
        }
        return if (ERROR_CODE.matches(code)) code else "http_${result.status}"
    }

    private companion object {
        const val PAIR_PATH = "/companion/v1/pair"
        const val DEVICE_PATH = "/companion/v1/device"
        const val REMINDERS_PATH = "/companion/v1/reminders"
        const val PUSH_PATH = "/companion/v1/push/subscription"
        const val PUSH_TEST_PATH = "/companion/v1/push/test"
        val PAIRING_SECRET = Regex("[A-Za-z0-9_-]{16,128}")
        val ERROR_CODE = Regex("[a-z][a-z0-9_]{0,63}")
    }
}
