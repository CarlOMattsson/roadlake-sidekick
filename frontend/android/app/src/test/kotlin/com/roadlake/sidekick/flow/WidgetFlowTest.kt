package com.roadlake.sidekick.flow

import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.support.JvmPhone
import com.roadlake.sidekick.today.EnqueueResult
import com.roadlake.sidekick.today.SyncResult
import com.roadlake.sidekick.today.TASK_A
import com.roadlake.sidekick.today.TASK_B
import com.roadlake.sidekick.today.TodayNotice
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
 * The widget's update flow without Android: what it draws ([TodayState], the same value the Glance content is built
 * from) and what a worker run ([com.roadlake.sidekick.widget.TodaySyncRun]) does to it, over a fake companion server.
 * Glance's own rendering and WorkManager's scheduling are not covered here.
 */
class WidgetFlowTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val phone by lazy { JvmPhone(folder.newFolder()) }
    private val completeA = "/companion/v1/tasks/$TASK_A/complete"
    private var retryScheduled = 0

    @After
    fun stopServer() = phone.close()

    private fun run(onlyIfStale: Boolean = false) = phone.process.syncRun.run(onlyIfStale) { retryScheduled++ }

    private fun ready() = phone.process.today.state() as TodayState.Ready

    @Test
    fun theWidgetFollowsThePairingFromConnectToRowsAndBack() {
        assertEquals(TodayState.NotPaired, phone.process.today.state())
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.server.addTask(TASK_B, "Ring banken")
        assertEquals(TodayState.Loading, phone.process.today.state())

        assertEquals(SyncResult.UPDATED, run())

        assertEquals(listOf("Köp mjölk", "Ring banken"), ready().snapshot.tasks.map { it.title })
        assertTrue(ready().pendingTaskIds.isEmpty())
        phone.process.client.unpair()
        assertEquals(TodayState.NotPaired, phone.process.today.state())
        assertEquals("one redraw at the start and one at the end of the pairing", 2, phone.process.widgetRedraws)
    }

    @Test
    fun aTapShowsTheRowAsPendingAtOnceAndTheNextRunSendsItAndDropsTheRow() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.server.addTask(TASK_B, "Ring banken")
        run()

        assertEquals(EnqueueResult.QUEUED, phone.process.today.enqueueCompletion(TASK_A))

        assertEquals(setOf(TASK_A), ready().pendingTaskIds)
        assertTrue("the tap itself sends nothing", phone.server.requestsTo("POST", completeA).isEmpty())
        assertEquals(SyncResult.UPDATED, run())
        assertEquals(1, phone.server.completionsApplied)
        assertEquals(listOf(TASK_B), ready().snapshot.tasks.map { it.id })
        assertTrue(ready().pendingTaskIds.isEmpty())
        assertEquals(1, ready().snapshot.total)
    }

    @Test
    fun aCacheThatCannotBeWrittenMakesTheRunAskForARetryAndALaterRunSucceeds() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.failCacheWrites = true

        assertEquals("the worker maps this to Result.retry()", SyncResult.RETRY, run())
        assertEquals(TodayState.Loading, phone.process.today.state())

        phone.failCacheWrites = false
        assertEquals(SyncResult.UPDATED, run())
        assertEquals(listOf("Köp mjölk"), ready().snapshot.tasks.map { it.title })
    }

    @Test
    fun aTaskChangedElsewhereIsAConflictTheWidgetShowsAndNeverResendsWithANewVersion() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        run()
        phone.process.today.enqueueCompletion(TASK_A)
        phone.server.editElsewhere(TASK_A)

        assertEquals(SyncResult.UPDATED, run())

        assertEquals("the server refused it once", 1, phone.server.requestsTo("POST", completeA).size)
        assertEquals(0, phone.server.completionsApplied)
        assertTrue(phone.process.outbox.pending().isEmpty())
        val state = ready()
        assertEquals(TodayNotice.CONFLICT, state.snapshot.notice)
        assertEquals("the row is back with the server's version", 2, state.snapshot.tasks.single().version)
    }

    @Test
    fun aDueRenewalComesBeforeTodayIsReadAndTodayIsReadWithTheNewCredential() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        val old = phone.server.validToken
        phone.server.renewAfter = "2026-11-01T12:00:00Z"
        phone.clock = IsoInstant.parse("2026-12-09T00:00:00Z")!!

        assertEquals(SyncResult.UPDATED, run())

        val after = phone.server.requests.drop(1) // the pairing exchange is the first request
        assertEquals(
            listOf("POST /companion/v1/device/renew", "GET /companion/v1/work/today"),
            after.map { "${it.method} ${it.path}" },
        )
        assertEquals("Bearer $old", after[0].headers["authorization"])
        assertEquals("Bearer ${phone.server.validToken}", after[1].headers["authorization"])
        assertEquals(0, retryScheduled)
    }

    @Test
    fun aRenewalWhoseAnswerWasLostSchedulesAnEarlyRetryAndTodayIsStillRead() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        phone.server.renewAfter = "2026-11-01T12:00:00Z"
        phone.clock = IsoInstant.parse("2026-12-09T00:00:00Z")!!
        phone.server.loseAnswersTo = "/companion/v1/device/renew"

        // The server rotated the token but the phone never heard: the old one is still good for the grace time.
        assertEquals(SyncResult.UPDATED, run())

        assertEquals(1, retryScheduled)
        assertEquals(listOf("Köp mjölk"), ready().snapshot.tasks.map { it.title })
    }

    @Test
    fun aRunForAFreshTodayWithNothingQueuedAsksNobodyAndALaterOneReadsAgain() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        run()
        val reads = phone.server.requestsTo("GET", "/companion/v1/work/today").size

        assertNull(run(onlyIfStale = true))
        assertEquals(reads, phone.server.requestsTo("GET", "/companion/v1/work/today").size)

        phone.clock += 61_000L
        assertEquals(SyncResult.UPDATED, run(onlyIfStale = true))
        assertEquals(reads + 1, phone.server.requestsTo("GET", "/companion/v1/work/today").size)
    }

    @Test
    fun aRevokedDeviceMakesTheWidgetAskToConnectAndLeavesNothingQueued() {
        phone.pair()
        phone.server.addTask(TASK_A, "Köp mjölk")
        run()
        phone.process.today.enqueueCompletion(TASK_A)
        phone.server.revokeDevice()

        assertEquals(SyncResult.NOT_PAIRED, run())

        assertEquals(TodayState.NotPaired, phone.process.today.state())
        assertFalse(phone.process.cache.hasData())
        assertFalse(phone.process.outbox.hasData())
        assertEquals(1, phone.process.pairingLosses)
        assertEquals("the widget redraws as the pairing ends", 2, phone.process.widgetRedraws)
    }
}
