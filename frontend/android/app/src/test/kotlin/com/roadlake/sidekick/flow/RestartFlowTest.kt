package com.roadlake.sidekick.flow

import com.roadlake.sidekick.companion.RenewalOutcome
import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.support.JvmPhone
import com.roadlake.sidekick.today.EnqueueResult
import com.roadlake.sidekick.today.SyncResult
import com.roadlake.sidekick.today.TASK_A
import com.roadlake.sidekick.today.TodayState
import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder

/**
 * What a killed and restarted process gets back: every test ends the [JvmPhone]'s process and starts a new one over the
 * files the old one wrote, with a fake companion server on a real socket. The pairing file stands in for the Keystore
 * store (see the instrumented lifecycle test for the real one).
 */
class RestartFlowTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val phone by lazy { JvmPhone(folder.newFolder()) }
    private val completePath = "/companion/v1/tasks/$TASK_A/complete"

    @After
    fun stopServer() = phone.close()

    private fun pairedWithOneTaskRead() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        assertEquals(SyncResult.UPDATED, phone.process.today.sync())
    }

    @Test
    fun theRenewedCredentialIsTheOneRestoredAfterARestart() {
        phone.pair()
        phone.server.renewAfter = "2026-11-01T12:00:00Z"
        phone.clock = PAST_RENEW_AFTER
        assertEquals(RenewalOutcome.RENEWED, phone.process.renewal.run())

        val restarted = phone.restart()

        val kept = restarted.store.load()!!
        assertEquals(phone.server.validToken, kept.token)
        assertEquals("Test phone", kept.deviceLabel)
        assertEquals("2026-10-08T12:00:00Z", kept.pairedAt)
        assertEquals(200, restarted.client.request("GET", "/companion/v1/work/today", null, null, null).status)
        assertEquals(
            "Bearer ${phone.server.validToken}",
            phone.server.requestsTo("GET", "/companion/v1/work/today").last().headers["authorization"],
        )
    }

    @Test
    fun theCachedTodayIsDrawnAfterARestartWithoutAnyNetwork() {
        pairedWithOneTaskRead()
        phone.server.offline = true
        val requestsBefore = phone.server.requests.size

        val state = phone.restart().today.state() as TodayState.Ready

        assertEquals(listOf("Köp mjölk"), state.snapshot.tasks.map { it.title })
        assertTrue(state.pendingTaskIds.isEmpty())
        assertEquals(requestsBefore, phone.server.requests.size)
    }

    @Test
    fun aQueuedCompletionIsSentAfterARestartWithTheKeyAndVersionOfTheTap() {
        pairedWithOneTaskRead()
        phone.server.offline = true
        assertEquals(EnqueueResult.QUEUED, phone.process.today.enqueueCompletion(TASK_A))
        val queued = phone.process.outbox.pending().single()
        assertEquals(SyncResult.RETRY, phone.process.today.sync())
        assertEquals("the failed attempt is counted", 1, phone.process.outbox.pending().single().attempts)

        val restarted = phone.restart()
        val restored = restarted.outbox.pending().single()
        assertEquals(queued.idempotencyKey, restored.idempotencyKey)
        assertEquals(queued.version, restored.version)
        assertEquals(setOf(TASK_A), (restarted.today.state() as TodayState.Ready).pendingTaskIds)
        phone.server.offline = false
        assertEquals(SyncResult.UPDATED, restarted.today.sync())

        assertEquals(1, phone.server.completionsApplied)
        assertEquals(queued.idempotencyKey, phone.server.requestsTo("POST", completePath).last().headers["idempotency-key"])
        assertTrue(restarted.outbox.pending().isEmpty())
        assertTrue((restarted.today.state() as TodayState.Ready).snapshot.tasks.isEmpty())
    }

    @Test
    fun aCompletionWhoseAnswerWasLostIsNotAppliedTwiceAfterARestart() {
        pairedWithOneTaskRead()
        phone.process.today.enqueueCompletion(TASK_A)
        phone.server.loseAnswersTo = completePath
        assertEquals(SyncResult.RETRY, phone.process.today.sync())
        assertEquals("the server applied it before the answer was lost", 1, phone.server.completionsApplied)

        phone.server.loseAnswersTo = null
        val restarted = phone.restart()
        assertEquals(1, restarted.outbox.pending().size)
        assertEquals(SyncResult.UPDATED, restarted.today.sync())

        assertEquals("the replay under the same key is not a second completion", 1, phone.server.completionsApplied)
        assertEquals(2, phone.server.requestsTo("POST", completePath).size)
        assertTrue(restarted.outbox.pending().isEmpty())
    }

    @Test
    fun aRevocationSeenAfterARestartClearsWhatTheRestartRestored() {
        pairedWithOneTaskRead()
        phone.process.today.enqueueCompletion(TASK_A)
        val restarted = phone.restart()
        assertTrue(restarted.cache.hasData() && restarted.outbox.hasData())
        phone.server.revokeDevice()

        assertEquals(SyncResult.NOT_PAIRED, restarted.today.sync())

        assertEquals(TodayState.NotPaired, restarted.today.state())
        assertFalse(restarted.cache.hasData())
        assertFalse(restarted.outbox.hasData())
        assertNull(restarted.store.load())
    }

    @Test
    fun theQuickRetryNoteSurvivesARestartAndOpensAgainAfterItsDelay() {
        phone.pair()
        phone.server.renewAfter = "2026-11-01T12:00:00Z"
        phone.clock = PAST_RENEW_AFTER
        phone.server.offline = true
        // The request may have reached the server: a quick retry, not the six-hour pause.
        assertEquals(RenewalOutcome.RETRY_SOON, phone.process.renewal.run())
        val asked = phone.server.requestsTo("POST", "/companion/v1/device/renew").size

        val restarted = phone.restart()
        assertEquals(RenewalOutcome.DEFERRED, restarted.renewal.run())
        assertEquals(
            "a restart does not ask the server again at once",
            asked,
            phone.server.requestsTo("POST", "/companion/v1/device/renew").size,
        )

        phone.server.offline = false
        phone.clock += 90_000L
        assertEquals(RenewalOutcome.RENEWED, restarted.renewal.run())
        assertEquals(phone.server.validToken, restarted.store.load()!!.token)
    }

    @Test
    fun theLongPauseAfterARefusedConnectionSurvivesARestart() {
        phone.pair()
        phone.clock = PAST_RENEW_AFTER
        phone.server.close() // the port refuses the connection: provably before the request was sent

        assertEquals(RenewalOutcome.RETRY_LATER, phone.process.renewal.run())
        phone.clock += 60 * 60 * 1000L

        assertEquals(RenewalOutcome.DEFERRED, phone.restart().renewal.run())
    }

    private companion object {
        val PAST_RENEW_AFTER = IsoInstant.parse("2026-12-09T00:00:00Z")!!
    }
}
