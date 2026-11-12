package com.roadlake.sidekick.companion

import com.roadlake.sidekick.push.IsoInstant
import com.roadlake.sidekick.today.MemoryTextStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.util.concurrent.CountDownLatch
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger
import kotlin.concurrent.thread

private const val ORIGIN = "https://sidekick.example"
private const val OLD = "rsc_abcdefghijklmnopqrstuvwxyz0123456789"
private const val NEW = "rsc_renewedrenewedrenewedrenewed012345"
private const val DUE = "2026-11-08T12:00:00Z"

/**
 * A store that holds one named thread inside its Nth `load()`, after the value was read: the exact moment in which a
 * read-modify-write without a lock would act on a stale pairing. The pause is long enough for the other thread to run
 * (without the lock it does, and the stale write follows); with the lock the other thread waits and the order is fixed.
 */
private class PausingStore(@Volatile var pairing: Pairing?) : PairingStore {
    @Volatile var pausedThread: String? = null

    @Volatile var pausedLoad = 0
    val paused = CountDownLatch(1)
    private val loads = AtomicInteger()

    override fun load(): Pairing? {
        val value = pairing
        if (Thread.currentThread().name == pausedThread && loads.incrementAndGet() == pausedLoad) {
            paused.countDown()
            Thread.sleep(PAUSE_MILLIS)
        }
        return value
    }

    override fun save(pairing: Pairing) {
        this.pairing = pairing
    }

    override fun clear() {
        pairing = null
    }

    private companion object {
        const val PAUSE_MILLIS = 400L
    }
}

private fun renewedBody() =
    """{"access_token":"$NEW","device":{"label":"Pixel","expires_at":"2027-02-08T12:00:00Z","renew_after":"2026-12-08T12:00:00Z"}}"""

class PairingRaceTest {
    private val now = IsoInstant.parse("2026-11-08T12:00:00Z")!!

    private fun pairing() = Pairing(ORIGIN, OLD, "Pixel", "2026-10-08T12:00:00Z", "2027-01-08T12:00:00Z", DUE)

    // The server keeps saying the renewal is due ([DUE]). A later date here would make a status refresh that runs before the
    // renewal push `renew_after` into the future; the renewal then correctly answers NOT_DUE and the test would depend on timing.
    private fun http() = object : HttpTransport {
        override fun execute(call: HttpCall): HttpResult = when (call.method) {
            "GET" -> HttpResult(200, """{"device":{"label":"Pixel","renew_after":"$DUE"}}""")
            "DELETE" -> HttpResult(204, "")
            else -> error("unexpected ${call.method}")
        }
    }

    private fun renewalOf(store: PairingStore) = TokenRenewal(store, { CompanionResponse(200, renewedBody()) }, MemoryTextStore()) { now }

    @Test
    fun aClearDuringARenewalWinsAndTheRenewedTokenDoesNotComeBack() {
        val store = PausingStore(pairing())
        val client = CompanionClient(store, http(), allowLocalCleartext = false)
        // Load 1 is the renewal's first look; load 2 is inside the store step, the stale-read window.
        store.pausedThread = "renewal"
        store.pausedLoad = 2
        val outcome = arrayOfNulls<RenewalOutcome>(1)
        val renewing = thread(name = "renewal") { outcome[0] = renewalOf(store).run() }
        assertTrue(store.paused.await(5, TimeUnit.SECONDS))
        val clearing = thread(name = "clear") { client.unpair() }
        renewing.join(10_000)
        clearing.join(10_000)

        assertNull("a clear must win over a renewal in progress", store.pairing)
        assertEquals(RenewalOutcome.RENEWED, outcome[0])
    }

    @Test
    fun aClearBeforeTheRenewedTokenArrivesLeavesNothingStored() {
        val store = PausingStore(pairing())
        val client = CompanionClient(store, http(), allowLocalCleartext = false)
        val renewal = TokenRenewal(
            store,
            {
                client.unpair()
                CompanionResponse(200, renewedBody())
            },
            MemoryTextStore(),
        ) { now }

        assertEquals(RenewalOutcome.UNPAIRED, renewal.run())
        assertNull(store.pairing)
    }

    @Test
    fun aStatusRefreshThatReadAnOldPairingDoesNotRevertARenewedToken() {
        val store = PausingStore(pairing())
        val client = CompanionClient(store, http(), allowLocalCleartext = false)
        // deviceStatus loads: 1 the record, 2 the request, 3 the refresh step (paused there, holding the old pairing).
        store.pausedThread = "status"
        store.pausedLoad = 3
        val status = thread(name = "status") { client.deviceStatus() }
        assertTrue(store.paused.await(5, TimeUnit.SECONDS))
        val renewing = thread(name = "renewal") { renewalOf(store).run() }
        status.join(10_000)
        renewing.join(10_000)

        assertEquals(NEW, store.pairing?.token)
    }

    @Test
    fun concurrentStatusCallsAndARenewalEndOnTheRenewedPairing() {
        val store = PausingStore(pairing())
        val client = CompanionClient(store, http(), allowLocalCleartext = false)
        val start = CountDownLatch(1)
        val workers = (1..4).map {
            thread {
                start.await()
                repeat(20) {
                    client.status()
                    client.deviceStatus()
                }
            }
        }
        val renewing = thread {
            start.await()
            renewalOf(store).run()
        }
        start.countDown()
        (workers + renewing).forEach { it.join(20_000) }

        assertEquals(NEW, store.pairing?.token)
    }

    /** A client whose revocation request runs [during] before it is answered, i.e. while the unpair is in flight. */
    private fun clientWhoseRevocationRuns(store: PairingStore, during: () -> Unit) = CompanionClient(
        store,
        object : HttpTransport {
            override fun execute(call: HttpCall): HttpResult {
                during()
                return HttpResult(204, "")
            }
        },
        allowLocalCleartext = false,
    )

    @Test
    fun anUnpairThatFinishesAfterANewPairingLeavesTheNewPairingAlone() {
        val store = PausingStore(pairing())
        val newer = Pairing(ORIGIN, NEW, "Tablet", "2026-11-08T12:00:00Z", "2027-02-08T12:00:00Z", DUE)
        val client = clientWhoseRevocationRuns(store) {
            store.clear()
            store.save(newer)
        }

        assertTrue(client.unpair())
        assertEquals(NEW, store.pairing?.token)
    }

    @Test
    fun anUnpairClearsTheSameDeviceUnderARenewedCredential() {
        val store = PausingStore(pairing())
        val client = clientWhoseRevocationRuns(store) { store.update(pairing().withRenewedToken(NEW, DeviceInfo.EMPTY)) }

        assertTrue(client.unpair())
        assertNull(store.pairing)
    }
}
