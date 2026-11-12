package com.roadlake.sidekick.companion

import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.today.TextStore
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

/** The one server route of the renewal; [CompanionClient.renew] is the real one. */
fun interface RenewalApi {
    fun renew(): CompanionResponse
}

enum class RenewalOutcome {
    /** `renew_after` has not come (or the server just said so, 409): nothing to do. */
    NOT_DUE,

    /** A new credential is stored and in use. */
    RENEWED,

    /** A failure not long ago: not tried again yet. */
    DEFERRED,

    /** This attempt failed for a reason that proves the server did not rotate the token (no connection, 429, ...): try much later. */
    RETRY_LATER,

    /**
     * The request may have reached the server (lost answer, timeout, 5xx, or the new credential could not be stored), so
     * the old token may already be replaced and is valid only for the server's short grace time. Try again within
     * [TokenRenewal.QUICK_RETRY_DELAY_MILLIS]; the caller must schedule that, also when the app is in the background.
     */
    RETRY_SOON,

    /** Not paired, or the server refused the credential (401): the pairing is gone and the usual flow has run. */
    UNPAIRED,
}

/**
 * Replaces the device credential before it expires (`POST /companion/v1/device/renew`), free of Android types so it is
 * unit tested on the JVM.
 *
 * When `now >= renew_after` (kept with the pairing; unknown counts as due, the server's 409 then tells it) the server is
 * asked. The new token is stored in the pairing store first and only then used: [CompanionClient] reads the store for
 * every request, so storing it is the switch. If it cannot be stored the old token stays; the server keeps it valid for
 * a few more minutes. A 409 moves `renew_after`. A 429 or a failure that provably came before the request was sent is
 * tried again later, but after a failure at most once per [FAILURE_PAUSE_MILLIS] (also across process restarts,
 * [retryState]). A 401 is the usual loss of the pairing, already handled by the client.
 *
 * The server rotates the token, and the old one is accepted only a few minutes more (or until the new one is used). So a
 * failure after which the request *may* have reached the server (a lost answer, a timeout, 5xx, a malformed 200, or a
 * save that failed after 200) must not wait six hours: the old token would be dead and the next call would end the
 * pairing. Such a failure is retried at most [QUICK_RETRIES] times, about [QUICK_RETRY_DELAY_MILLIS] apart ([RETRY_SOON];
 * the count lives in [retryState]); only then does the six-hour pause apply. The token is never logged.
 *
 * A run belongs to the pairing it began under ([PairingGeneration]): the request is pinned to it, and the pause and the
 * quick-retry count are written only while that pairing is current, so a failure of an old pairing's renewal cannot
 * hold back the renewal of the next one. [clearLocal] removes that note when a pairing ends.
 */
class TokenRenewal(
    private val store: PairingStore,
    private val api: RenewalApi,
    private val retryState: TextStore,
    private val generation: PairingGeneration = PairingGeneration(),
    private val now: () -> Long,
) {
    @Synchronized
    fun run(): RenewalOutcome {
        val captured = generation.current()
        return generation.pinned(captured) { runFor(captured) }
    }

    /** Every end of a pairing: the pause and the retry count were earned by that pairing's credential. */
    @Throws(java.io.IOException::class)
    fun clearLocal() = retryState.erase()

    private fun runFor(captured: Long): RenewalOutcome {
        val pairing = store.load() ?: return RenewalOutcome.UNPAIRED
        val time = now()
        val dueAt = pairing.renewAfter?.let(IsoInstant::parse)
        if (dueAt != null && time < dueAt) return RenewalOutcome.NOT_DUE
        if (time < retryNotBefore()) return RenewalOutcome.DEFERRED

        val response = try {
            api.renew()
        } catch (e: CompanionException) {
            return when {
                e.code == "not_paired" -> RenewalOutcome.UNPAIRED
                e.beforeSend -> failed(captured, time, null)
                else -> maybeRotated(captured, time)
            }
        }
        return when (response.status) {
            200 -> accept(captured, pairing, response, time)

            401 -> {
                generation.runIfCurrent(captured) { retryState.delete() }
                RenewalOutcome.UNPAIRED
            }

            409 -> notDue(captured, pairing, response, time)

            429 -> failed(captured, time, response.retryAfterSeconds)

            in 500..599 -> maybeRotated(captured, time)

            else -> failed(captured, time, null)
        }
    }

    private fun accept(captured: Long, used: Pairing, response: CompanionResponse, time: Long): RenewalOutcome {
        val token: String
        val device: DeviceInfo
        try {
            val json = JSONObject(response.body)
            token = json.getString("access_token")
            device = DeviceInfo.ofAnswer(json)
        } catch (_: JSONException) {
            return maybeRotated(captured, time)
        }
        if (!CredentialFormat.TOKEN.matches(token)) return maybeRotated(captured, time)
        // The pairing ended or was replaced while the request was in flight: the new token belongs to nobody.
        // Check and store are one step: a clear (or a new pairing) cannot slip in between and be undone by this write.
        val stored = PairingLock.atomically {
            val current = store.load()
            if (current == null || current.token != used.token) {
                null
            } else {
                try {
                    store.update(current.withRenewedToken(token, device))
                    true
                } catch (_: CompanionException) {
                    false
                }
            }
        }
        return when (stored) {
            null -> RenewalOutcome.UNPAIRED

            true -> {
                generation.runIfCurrent(captured) { retryState.delete() }
                RenewalOutcome.RENEWED
            }

            // Stored nothing: the old token is still the one in use, valid a few minutes more, so ask again soon.
            false -> maybeRotated(captured, time)
        }
    }

    private fun notDue(captured: Long, used: Pairing, response: CompanionResponse, time: Long): RenewalOutcome {
        if (TestPushResult.reasonOf(response.body) != "renewal_not_due") return failed(captured, time, null)
        val renewAfter = renewAfterOf(response.body) ?: return failed(captured, time, null)
        // The server moved the date; it is in the future unless clocks differ, then the pause below protects the server.
        val moved = IsoInstant.parse(renewAfter)?.let { it > time } == true
        if (!moved) return failed(captured, time, null)
        val stored = PairingLock.atomically {
            val current = store.load()
            if (current == null || current.token != used.token) {
                true
            } else {
                try {
                    store.update(current.withRenewAfter(renewAfter))
                    true
                } catch (_: CompanionException) {
                    false
                }
            }
        }
        if (!stored) return failed(captured, time, null)
        return RenewalOutcome.NOT_DUE
    }

    private fun renewAfterOf(body: String): String? = try {
        val json = JSONObject(body)
        (json.opt("renew_after") as? String) ?: DeviceInfo.of(json.optJSONObject("device")).renewAfter
    } catch (_: JSONException) {
        null
    }

    private fun failed(captured: Long, time: Long, retryAfterSeconds: Int?): RenewalOutcome {
        val pause = maxOf(FAILURE_PAUSE_MILLIS, (retryAfterSeconds ?: 0) * 1000L)
        writeState(captured, RetryState(time + pause, 0))
        return RenewalOutcome.RETRY_LATER
    }

    /** The request may have reached the server: a few quick retries inside its grace time, then the long pause. */
    private fun maybeRotated(captured: Long, time: Long): RenewalOutcome {
        val used = readState().quickRetries
        if (used >= QUICK_RETRIES) return failed(captured, time, null)
        // Without a place to remember the count the quick retries could repeat forever: then only the next trigger asks.
        // (The same when the pairing has changed meanwhile: its renewal is not ours to schedule.)
        if (!writeState(captured, RetryState(time + QUICK_RETRY_EARLIEST_MILLIS, used + 1))) return RenewalOutcome.RETRY_LATER
        return RenewalOutcome.RETRY_SOON
    }

    private class RetryState(val notBefore: Long, val quickRetries: Int)

    private fun writeState(captured: Long, state: RetryState): Boolean {
        var written = false
        generation.runIfCurrent(captured) {
            written = try {
                retryState.write(JSONObject().put("not_before", state.notBefore).put("quick_retries", state.quickRetries).toString())
                true
            } catch (_: IOException) {
                // Without a place to remember, the next trigger asks again; the triggers are few.
                false
            }
        }
        return written
    }

    /** Also reads the plain number older versions wrote. A damaged note counts as none. */
    private fun readState(): RetryState {
        return try {
            val text = retryState.read()?.trim() ?: return RetryState(0L, 0)
            text.toLongOrNull()?.let { return RetryState(it, 0) }
            val json = JSONObject(text)
            RetryState(json.optLong("not_before", 0L), json.optInt("quick_retries", 0).coerceIn(0, QUICK_RETRIES))
        } catch (_: JSONException) {
            RetryState(0L, 0)
        } catch (_: IOException) {
            RetryState(0L, 0)
        }
    }

    private fun retryNotBefore(): Long = readState().notBefore

    companion object {
        const val FAILURE_PAUSE_MILLIS = 6 * 60 * 60 * 1000L

        /** How many quick retries follow a failure that may have rotated the token (the server's grace is 10 minutes). */
        const val QUICK_RETRIES = 3

        /** The delay the caller schedules for [RenewalOutcome.RETRY_SOON]. */
        const val QUICK_RETRY_DELAY_MILLIS = 90_000L

        /** A little less than the delay, so a job that starts a moment early by the clock is not turned away. */
        private const val QUICK_RETRY_EARLIEST_MILLIS = 60_000L
    }
}
