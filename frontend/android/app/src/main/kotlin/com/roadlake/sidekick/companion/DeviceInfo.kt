package com.roadlake.sidekick.companion

import com.roadlake.sidekick.push.IsoInstant
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * The `device` object of the companion API (pairing, renewal and `GET /device`). A field that is missing or not text is
 * null. [enabledRooms] is the answer's top-level `enabled_rooms` (the rooms the instance shows), null when the server
 * does not say (an older server), which the page reads as every room. [ownerTimeZone] is the top-level `timezone` (the
 * owner's zone, [OwnerZone]), null when the server does not say or names a zone this phone does not know.
 * [pushEnabled] is the top-level `push_enabled` (whether the server delivers push), null when the server does not say
 * or it is not a boolean (unknown: the page then leaves its push row as it is).
 */
class DeviceInfo(
    val label: String?,
    val createdAt: String?,
    val expiresAt: String?,
    val renewAfter: String?,
    val enabledRooms: List<String>? = null,
    val ownerTimeZone: String? = null,
    val pushEnabled: Boolean? = null,
) {
    companion object {
        val EMPTY = DeviceInfo(null, null, null, null)

        /** [device] is the `device` object itself; only ISO instants are kept, so nothing odd reaches the page. */
        fun of(device: JSONObject?): DeviceInfo {
            device ?: return EMPTY
            return DeviceInfo(
                label = (device.opt("label") as? String)?.ifEmpty { null },
                createdAt = instant(device.opt("created_at")),
                expiresAt = instant(device.opt("expires_at")),
                renewAfter = instant(device.opt("renew_after")),
            )
        }

        /** The `device` and `enabled_rooms` of a response body such as `{"device":{...}}`, or [EMPTY] when the body is not that. */
        fun ofBody(body: String): DeviceInfo = try {
            ofAnswer(JSONObject(body))
        } catch (_: JSONException) {
            EMPTY
        }

        /** The `device` object and the top-level `enabled_rooms` of an answer that is already parsed. */
        fun ofAnswer(answer: JSONObject): DeviceInfo {
            val device = of(answer.optJSONObject("device"))
            val rooms = roomsOf(answer.optJSONArray("enabled_rooms"))
            val zone = OwnerZone.idOf(answer.opt("timezone"))
            val push = answer.opt("push_enabled") as? Boolean
            return DeviceInfo(device.label, device.createdAt, device.expiresAt, device.renewAfter, rooms, zone, push)
        }

        /** Room names only (lower-case letters, at most ten): a list that is anything else is not kept. */
        fun roomsOf(array: JSONArray?): List<String>? {
            array ?: return null
            if (array.length() == 0 || array.length() > MAX_ROOMS) return null
            val rooms = (0 until array.length()).map { array.opt(it) as? String ?: return null }
            return rooms.takeIf { list -> list.all { ROOM_NAME.matches(it) } }
        }

        private const val MAX_ROOMS = 10
        private val ROOM_NAME = Regex("[a-z]{1,16}")

        private fun instant(value: Any?): String? = (value as? String)?.takeIf { IsoInstant.parse(it) != null }
    }
}

/** What `deviceStatus()` tells the page. No token. */
class DeviceStatus(
    val paired: Boolean,
    val name: String?,
    val pairedAt: String?,
    val expiresAt: String?,
    val enabledRooms: List<String>? = null,
    val ownerTimeZone: String? = null,
    val pushEnabled: Boolean? = null,
) {
    companion object {
        val UNPAIRED = DeviceStatus(paired = false, name = null, pairedAt = null, expiresAt = null)

        fun of(pairing: Pairing) = DeviceStatus(
            true,
            pairing.deviceLabel,
            pairing.pairedAt,
            pairing.expiresAt,
            pairing.enabledRooms,
            pairing.ownerTimeZone,
            pairing.pushEnabled,
        )
    }
}

enum class TestPushOutcome(val wire: String) {
    QUEUED("queued"),
    RATE_LIMITED("rate_limited"),
    NO_SUBSCRIPTION("no_subscription"),
    DISABLED("disabled"),
    OFFLINE("offline"),
    UNPAIRED("unpaired"),
}

/** What `sendTestPush()` tells the page. [retryAfterSeconds] is set for [TestPushOutcome.RATE_LIMITED] when the server said. */
class TestPushResult(val outcome: TestPushOutcome, val retryAfterSeconds: Int? = null) {
    companion object {
        /** The mapping of `POST /companion/v1/push/test`: 202, 429, 409 `no_subscription`, 404 and 401; the rest is "offline". */
        fun of(response: CompanionResponse): TestPushResult = when (response.status) {
            202 -> TestPushResult(TestPushOutcome.QUEUED)
            429 -> TestPushResult(TestPushOutcome.RATE_LIMITED, response.retryAfterSeconds)
            409 -> if (reasonOf(response.body) == "no_subscription") TestPushResult(TestPushOutcome.NO_SUBSCRIPTION) else OFFLINE
            404 -> TestPushResult(TestPushOutcome.DISABLED)
            401 -> TestPushResult(TestPushOutcome.UNPAIRED)
            else -> OFFLINE
        }

        val UNPAIRED = TestPushResult(TestPushOutcome.UNPAIRED)
        val OFFLINE = TestPushResult(TestPushOutcome.OFFLINE)

        /** The `reason` of a problem body (`application/problem+json`), or null. */
        fun reasonOf(body: String): String? = try {
            JSONObject(body).optString("reason").ifEmpty { null }
        } catch (_: JSONException) {
            null
        }
    }
}

/** The shapes the app accepts for a device credential in a server answer. */
object CredentialFormat {
    val TOKEN = Regex("[A-Za-z0-9_-]{8,256}")
}
