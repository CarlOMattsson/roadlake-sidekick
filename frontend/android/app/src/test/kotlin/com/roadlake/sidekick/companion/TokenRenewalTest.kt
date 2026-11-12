package com.roadlake.sidekick.companion

import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.today.MemoryTextStore
import com.roadlake.sidekick.today.ScriptedHttp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

private const val ORIGIN = "https://sidekick.example"
private const val OLD = "rsc_abcdefghijklmnopqrstuvwxyz0123456789"
private const val NEW = "rsc_renewedrenewedrenewedrenewed012345"
private const val DUE = "2026-11-08T12:00:00Z"
private const val LATER = "2026-12-08T12:00:00Z"

private fun at(iso: String) = IsoInstant.parse(iso)!!

/** A store whose `update` can be made to fail, and which counts clears (a renewal must never clear). */
private class FlakyStore(var pairing: Pairing?, var failUpdate: Boolean = false) : PairingStore {
    var clears = 0
    var saves = 0

    override fun load() = pairing

    override fun save(pairing: Pairing) {
        saves++
        this.pairing = pairing
    }

    override fun update(pairing: Pairing) {
        if (failUpdate) throw CompanionException("secure_storage")
        this.pairing = pairing
    }

    override fun clear() {
        clears++
        pairing = null
    }
}

private fun renewedBody(token: String = NEW, expires: String = "2027-02-08T12:00:00Z", renewAfter: String = LATER) =
    """{"token_type":"Bearer","access_token":"$token","device":{"id":"d1","label":"Pixel","expires_at":"$expires","renew_after":"$renewAfter"}}"""

class TokenRenewalTest {
    private var now = at("2026-11-08T12:00:00Z")
    private val retry = MemoryTextStore()

    private fun pairing(renewAfter: String? = DUE) =
        Pairing(ORIGIN, OLD, "Pixel", "2026-10-08T12:00:00Z", "2027-01-08T12:00:00Z", renewAfter)

    private fun renewal(store: PairingStore, answer: () -> CompanionResponse, calls: MutableList<Unit> = mutableListOf()) =
        TokenRenewal(store, {
            calls += Unit
            answer()
        }, retry) { now }

    @Test
    fun beforeRenewAfterNothingIsAsked() {
        val store = FlakyStore(pairing("2026-11-08T12:00:01Z"))
        val calls = mutableListOf<Unit>()
        assertEquals(RenewalOutcome.NOT_DUE, renewal(store, { error("must not be called") }, calls).run())
        assertTrue(calls.isEmpty())
    }

    @Test
    fun whenDueTheNewTokenIsStoredWithItsDates() {
        val store = FlakyStore(pairing())
        assertEquals(RenewalOutcome.RENEWED, renewal(store, { CompanionResponse(200, renewedBody()) }).run())
        val kept = store.pairing!!
        assertEquals(NEW, kept.token)
        assertEquals("2027-02-08T12:00:00Z", kept.expiresAt)
        assertEquals(LATER, kept.renewAfter)
        assertEquals("2026-10-08T12:00:00Z", kept.pairedAt)
        assertEquals("Pixel", kept.deviceLabel)
        assertEquals(ORIGIN, kept.serverOrigin)
        assertEquals(0, store.clears)
        assertEquals(0, store.saves)
        assertNull(retry.text)
    }

    @Test
    fun aRenewalKeepsTheServersPushStateCurrentAndAnOlderServerKeepsTheStoredOne() {
        val store = FlakyStore(pairing())
        val body = renewedBody().replace("\"device\"", "\"push_enabled\":false,\"device\"")
        assertEquals(RenewalOutcome.RENEWED, renewal(store, { CompanionResponse(200, body) }).run())
        assertEquals(false, store.pairing!!.pushEnabled)
        store.pairing = store.pairing!!.withRenewAfter(DUE)
        assertEquals(RenewalOutcome.RENEWED, renewal(store, { CompanionResponse(200, renewedBody()) }).run())
        assertEquals(false, store.pairing!!.pushEnabled)
    }

    @Test
    fun anUnknownRenewAfterCountsAsDue() {
        val store = FlakyStore(pairing(renewAfter = null))
        assertEquals(RenewalOutcome.RENEWED, renewal(store, { CompanionResponse(200, renewedBody()) }).run())
    }

    @Test
    fun theNewTokenIsUsedByTheNextRequestAfterItWasStored() {
        val store = FlakyStore(pairing())
        val http = ScriptedHttp()
        http.on { call -> if (call.url.endsWith("/device/renew")) HttpResult(200, renewedBody()) else HttpResult(200, "{}") }
        val client = CompanionClient(store, http, allowLocalCleartext = false)
        assertEquals(RenewalOutcome.RENEWED, TokenRenewal(store, { client.renew() }, retry) { now }.run())
        client.request("GET", "/companion/v1/work/today", null, null, null)
        assertEquals("Bearer $OLD", http.calls[0].headers["Authorization"])
        assertEquals("POST", http.calls[0].method)
        assertNull(http.calls[0].body)
        assertEquals("Bearer $NEW", http.calls[1].headers["Authorization"])
    }

    @Test
    fun aFailedSaveKeepsTheOldTokenAndPausesTheNextTryUntilTheQuickRetry() {
        val store = FlakyStore(pairing(), failUpdate = true)
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { CompanionResponse(200, renewedBody()) }, calls)
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        assertEquals(OLD, store.pairing!!.token)
        assertEquals(0, store.clears)
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        assertEquals(1, calls.size)
    }

    @Test
    fun aSaveThatFailedAfter200IsRetriedWithinTheGraceTimeAndSucceeds() {
        val store = FlakyStore(pairing(), failUpdate = true)
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { CompanionResponse(200, renewedBody()) }, calls)
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        store.failUpdate = false
        now += TokenRenewal.QUICK_RETRY_DELAY_MILLIS
        assertEquals(RenewalOutcome.RENEWED, run.run())
        assertEquals(NEW, store.pairing!!.token)
        assertEquals(2, calls.size)
        assertNull(retry.text)
        assertEquals(0, store.clears)
    }

    @Test
    fun aLostAnswerIsRetriedWithinTheGraceTimeAndSucceeds() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        var lost = true
        val run = renewal(store, { if (lost) throw CompanionException("timeout") else CompanionResponse(200, renewedBody()) }, calls)
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        assertTrue(TokenRenewal.QUICK_RETRY_DELAY_MILLIS in 60_000L..120_000L)
        lost = false
        now += TokenRenewal.QUICK_RETRY_DELAY_MILLIS
        assertEquals(RenewalOutcome.RENEWED, run.run())
        assertEquals(NEW, store.pairing!!.token)
        assertNull(retry.text)
    }

    @Test
    fun anAmbiguousNetworkFailureAnAServerErrorAndAMalformed200AreRetriedSoon() {
        for (answer in listOf<() -> CompanionResponse>(
            { throw CompanionException("network") },
            { CompanionResponse(503, "") },
            { CompanionResponse(200, """{"access_token":"x y"}""") },
        )) {
            retry.delete()
            val store = FlakyStore(pairing())
            assertEquals(RenewalOutcome.RETRY_SOON, renewal(store, answer).run())
            assertEquals(OLD, store.pairing!!.token)
        }
    }

    @Test
    fun afterThreeQuickRetriesTheSixHourPauseApplies() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { throw CompanionException("timeout") }, calls)
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        repeat(TokenRenewal.QUICK_RETRIES - 1) {
            now += TokenRenewal.QUICK_RETRY_DELAY_MILLIS
            assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        }
        now += TokenRenewal.QUICK_RETRY_DELAY_MILLIS
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        assertEquals(1 + TokenRenewal.QUICK_RETRIES, calls.size)
        now += 5 * 3600_000L
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        now += 61 * 60_000L
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        assertEquals(2 + TokenRenewal.QUICK_RETRIES, calls.size)
    }

    @Test
    fun theQuickRetryIsNotAskedBeforeItsTime() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { throw CompanionException("timeout") }, calls)
        assertEquals(RenewalOutcome.RETRY_SOON, run.run())
        now += 30_000L
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        assertEquals(1, calls.size)
    }

    @Test
    fun aFailureBeforeSendingKeepsTheSixHourPause() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { throw CompanionException("network", beforeSend = true) }, calls)
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        now += 5 * 3600_000L
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        now += 61 * 60_000L
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        assertEquals(2, calls.size)
        assertEquals(OLD, store.pairing!!.token)
    }

    @Test
    fun aPlainNumberNoteFromAnOlderVersionStillPauses() {
        retry.text = (now + 3600_000L).toString()
        val calls = mutableListOf<Unit>()
        assertEquals(RenewalOutcome.DEFERRED, renewal(FlakyStore(pairing()), { error("no") }, calls).run())
        assertTrue(calls.isEmpty())
    }

    @Test
    fun aMalformedAnswerStoresNothing() {
        val store = FlakyStore(pairing())
        assertEquals(RenewalOutcome.RETRY_SOON, renewal(store, { CompanionResponse(200, """{"access_token":"x y"}""") }).run())
        assertEquals(OLD, store.pairing!!.token)
    }

    @Test
    fun a409MovesRenewAfterAndIsNotAFailure() {
        val store = FlakyStore(pairing())
        val body = """{"code":"conflict","reason":"renewal_not_due","renew_after":"$LATER"}"""
        assertEquals(RenewalOutcome.NOT_DUE, renewal(store, { CompanionResponse(409, body) }).run())
        assertEquals(LATER, store.pairing!!.renewAfter)
        assertEquals(OLD, store.pairing!!.token)
        assertNull(retry.text)
    }

    @Test
    fun a409WithoutAFutureDateIsTreatedAsAFailure() {
        val store = FlakyStore(pairing())
        val body = """{"reason":"renewal_not_due","renew_after":"2026-11-01T00:00:00Z"}"""
        assertEquals(RenewalOutcome.RETRY_LATER, renewal(store, { CompanionResponse(409, body) }).run())
        assertEquals(DUE, store.pairing!!.renewAfter)
    }

    @Test
    fun a429WaitsAtLeastSixHoursAndTheServersRetryAfterIfLonger() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { CompanionResponse(429, "{}", retryAfterSeconds = 8 * 3600) }, calls)
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        now += 7 * 3600_000L
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        now += 2 * 3600_000L
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        assertEquals(2, calls.size)
    }

    @Test
    fun aNoConnectionFailureTriesAgainOnlyAfterSixHours() {
        val store = FlakyStore(pairing())
        val calls = mutableListOf<Unit>()
        val run = renewal(store, { throw CompanionException("network", beforeSend = true) }, calls)
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        now += 5 * 3600_000L
        assertEquals(RenewalOutcome.DEFERRED, run.run())
        now += 61 * 60_000L
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        assertEquals(2, calls.size)
        assertEquals(OLD, store.pairing!!.token)
    }

    @Test
    fun aServerErrorIsRetriedSoon() {
        val store = FlakyStore(pairing())
        assertEquals(RenewalOutcome.RETRY_SOON, renewal(store, { CompanionResponse(503, "") }).run())
        assertNotNull(retry.text)
    }

    @Test
    fun aWriteFailureOfTheRetryNoteDoesNotBreakTheRun() {
        val store = FlakyStore(pairing())
        retry.failWrites = true
        assertEquals(RenewalOutcome.RETRY_LATER, renewal(store, { throw CompanionException("timeout") }).run())
        assertEquals(RenewalOutcome.RETRY_LATER, renewal(store, { throw CompanionException("network", beforeSend = true) }).run())
    }

    @Test
    fun a401ThroughTheClientEndsThePairingTheUsualWay() {
        val store = FlakyStore(pairing())
        val http = ScriptedHttp()
        http.on { HttpResult(401, """{"code":"unauthorized"}""") }
        var lost = 0
        val client = CompanionClient(store, http, allowLocalCleartext = false, onPairingLost = { lost++ })
        assertEquals(RenewalOutcome.UNPAIRED, TokenRenewal(store, { client.renew() }, retry) { now }.run())
        assertNull(store.pairing)
        assertEquals(1, lost)
        assertEquals(1, store.clears)
    }

    @Test
    fun withoutAPairingNothingIsAsked() {
        val calls = mutableListOf<Unit>()
        assertEquals(RenewalOutcome.UNPAIRED, renewal(FlakyStore(null), { error("no") }, calls).run())
        assertTrue(calls.isEmpty())
    }

    @Test
    fun aFailureOfAnEndedPairingLeavesNoPauseAgainstTheNextOne() {
        val generation = PairingGeneration()
        val store = FlakyStore(pairing())
        val run = TokenRenewal(
            store,
            {
                generation.advance()
                throw CompanionException("timeout")
            },
            retry,
            generation,
        ) { now }
        assertEquals(RenewalOutcome.RETRY_LATER, run.run())
        assertNull(retry.text)
    }

    @Test
    fun aPairingEndedBeforeTheRequestIsSentRenewsNothingForTheNewOne() {
        val generation = PairingGeneration()
        val store = FlakyStore(pairing())
        val http = ScriptedHttp()
        http.on { HttpResult(200, renewedBody()) }
        val client = CompanionClient(store, http, allowLocalCleartext = false, generation = generation)
        val run = TokenRenewal(
            store,
            {
                // The pairing is replaced between the renewal reading its state and sending: the new device is not renewed.
                generation.advance()
                client.renew()
            },
            retry,
            generation,
        ) { now }
        assertEquals(RenewalOutcome.UNPAIRED, run.run())
        assertTrue(http.calls.isEmpty())
        assertNull(retry.text)
    }

    @Test
    fun endingAPairingRemovesTheRetryNote() {
        retry.text = """{"not_before":9999999999999,"quick_retries":2}"""
        TokenRenewal(FlakyStore(null), { error("no") }, retry) { now }.clearLocal()
        assertNull(retry.text)
    }

    @Test
    fun aPairingReplacedMeanwhileDoesNotGetTheOldDevicesToken() {
        val store = FlakyStore(pairing())
        val run = renewal(store, {
            store.pairing = Pairing(ORIGIN, "rsc_otherotherotherotherother0123456789", "Other")
            CompanionResponse(200, renewedBody())
        })
        assertEquals(RenewalOutcome.UNPAIRED, run.run())
        assertEquals("rsc_otherotherotherotherother0123456789", store.pairing!!.token)
    }
}
