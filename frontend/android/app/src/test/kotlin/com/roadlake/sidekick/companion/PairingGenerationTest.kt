package com.roadlake.sidekick.companion

import com.roadlake.sidekick.today.ClearingPairingStore
import com.roadlake.sidekick.today.MemoryPairingStore
import com.roadlake.sidekick.today.ScriptedHttp
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import kotlin.concurrent.thread

class PairingGenerationTest {
    private val generation = PairingGeneration()
    private val http = ScriptedHttp().apply { on { HttpResult(200, "{}") } }
    private val store = ClearingPairingStore(MemoryPairingStore(), {}, {}, generation)
    private val client = CompanionClient(store, http, allowLocalCleartext = false, generation = generation)
    private val newer = Pairing("https://sidekick.example", "rsc_newnewnewnewnewnewnewnew0123456789", null)

    private fun today() = client.request("GET", "/companion/v1/work/today", null, null, null)

    @Test
    fun aWriteRunsOnlyWhileItsGenerationIsCurrent() {
        val captured = generation.current()
        var writes = 0
        assertTrue(generation.runIfCurrent(captured) { writes++ })
        generation.advance()
        assertFalse(generation.runIfCurrent(captured) { writes++ })
        assertEquals(1, writes)
        assertTrue(generation.runIfCurrent(generation.current()) { writes++ })
    }

    @Test
    fun everyStartAndEndOfAPairingAdvancesTheGenerationButARenewalDoesNot() {
        val start = generation.current()
        store.save(newer)
        val saved = generation.current()
        assertTrue(saved > start)
        store.update(newer)
        assertEquals(saved, generation.current())
        store.clear()
        assertTrue(generation.current() > saved)
    }

    @Test
    fun aRequestPinnedToAnEarlierGenerationIsRefusedBeforeItIsSent() {
        val captured = generation.current()
        store.save(newer)
        http.calls.clear()
        try {
            generation.pinned(captured) { today() }
            fail("expected not_paired")
        } catch (e: CompanionException) {
            assertEquals("not_paired", e.code)
        }
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun aRequestPinnedToTheCurrentGenerationIsSentWithItsCredential() {
        store.save(newer)
        val answer = generation.pinned(generation.current()) { today() }
        assertEquals(200, answer.status)
        assertEquals("Bearer ${newer.token}", http.calls.single().headers["Authorization"])
    }

    @Test
    fun aRequestOutsideAPinIsNotRefused() {
        store.save(newer)
        generation.advance()
        assertEquals(200, today().status)
    }

    @Test
    fun thePinEndsWithTheBlockAndNestedPinsRestoreTheOuterOne() {
        store.save(newer)
        val outer = generation.current()
        generation.advance()
        generation.pinned(generation.current()) {
            generation.pinned(outer) { assertNull(runCatching { today() }.getOrNull()) }
            assertEquals(200, today().status)
        }
        assertEquals(200, today().status)
    }

    @Test
    fun aCallBoundWhenItArrivedIsRefusedAfterThePairingChangedWhileItWaitedInThePool() {
        val arrivedUnder = generation.current()
        val task = generation.bindNow { captured ->
            assertEquals(arrivedUnder, captured)
            today()
        }
        // The call waits in a busy pool; the phone is unpaired and paired again before a thread picks it up.
        store.clear()
        store.save(newer)
        http.calls.clear()
        val ran = java.util.concurrent.Executors.newSingleThreadExecutor()
        try {
            val error = try {
                ran.submit(task).get(5, TimeUnit.SECONDS)
                null
            } catch (e: java.util.concurrent.ExecutionException) {
                e.cause as? CompanionException
            }
            assertEquals("not_paired", error?.code)
        } finally {
            ran.shutdownNow()
        }
        assertTrue(http.calls.isEmpty()) // nothing was sent with the new pairing's credential
    }

    @Test
    fun aCallBoundWhenItArrivedRunsAsBeforeWhenThePairingDidNotChange() {
        store.save(newer)
        val task = generation.bindNow { today().status }
        assertEquals(200, task())
        assertEquals(1, http.calls.size)
    }

    @Test
    fun aPairingChangeWaitsForAWriteThatIsInProgressAndThenEndsIt() {
        val captured = generation.current()
        val inside = CountDownLatch(1)
        val release = CountDownLatch(1)
        var wrote = false
        val writing = thread {
            generation.runIfCurrent(captured) {
                inside.countDown()
                release.await(5, TimeUnit.SECONDS)
                wrote = true
            }
        }
        assertTrue(inside.await(5, TimeUnit.SECONDS))
        // The change takes the same lock the write holds (as pair() and unpair() do), so it follows the write, not precedes it.
        val changing = thread { PairingLock.atomically { generation.advance() } }
        release.countDown()
        writing.join(10_000)
        changing.join(10_000)
        assertTrue(wrote)
        assertFalse(generation.runIfCurrent(captured) { wrote = false })
        assertTrue(wrote)
    }
}
