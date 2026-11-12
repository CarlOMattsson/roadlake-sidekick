package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStatus
import com.roadlake.sidekick.companion.PairingStore
import com.roadlake.sidekick.companion.UnreadablePairingException
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Test

private val PAIRING = Pairing("https://sidekick.example", "rsc_abcdefghijklmnopqrstuvwxyz0123456789", "Pixel", "2026-11-01T10:00:00Z")

/** A store that behaves like [com.roadlake.sidekick.companion.KeystorePairingStore] when its record or its key is bad. */
private class FaultyStore(var pairing: Pairing? = PAIRING) : PairingStore {
    var unreadable = false
    var failClear = false
    var clears = 0

    override fun load(): Pairing? {
        if (unreadable) throw UnreadablePairingException()
        return pairing
    }

    override fun save(pairing: Pairing) {
        this.pairing = pairing
    }

    override fun clear() {
        clears++
        if (failClear) throw CompanionException("secure_storage")
        pairing = null
        unreadable = false
    }
}

class PairingStorageFailureTest {
    private val delegate = FaultyStore()
    private val marker = MemoryTextStore()
    private val generation = PairingGeneration()
    private var localCleared = 0
    private var changed = 0
    private var lost = 0
    private val logged = mutableListOf<String>()

    private fun store(marker: MemoryTextStore? = this.marker) = ClearingPairingStore(
        delegate,
        { localCleared++ },
        { changed++ },
        generation,
        onLost = { lost++ },
        onFailure = { logged += it },
        marker = marker,
    )

    @Test
    fun anUnreadableStoredPairingTakesTheNormalUnpairPath() {
        val store = store()
        val before = generation.current()
        delegate.unreadable = true

        assertNull(store.load())

        assertEquals(1, delegate.clears)
        assertNull(delegate.pairing)
        assertEquals(1, localCleared)
        assertEquals(1, changed)
        assertEquals(1, lost) // the page is told, so it shows the pairing form with "the connection has ended"
        assertTrue(generation.current() > before)
        assertNull(marker.text)
        assertNull(store.load()) // and it stays unpaired
        assertEquals(1, lost)
        assertTrue(logged.none { it.contains("rsc_") || it.contains("sidekick.example") })
    }

    @Test
    fun theClientReadsAnUnreadablePairingAsNotPaired() {
        val http = ScriptedHttp()
        val client = CompanionClient(store(), http, allowLocalCleartext = false, generation = generation)
        delegate.unreadable = true

        assertEquals(PairingStatus.UNPAIRED, client.status())
        assertEquals(1, lost)
        assertTrue(http.calls.isEmpty())
    }

    @Test
    fun aFailingClearStillClearsLocalDataAndMarksThePhoneDisconnected() {
        val store = store()
        delegate.failClear = true

        store.clear() // does not throw

        assertEquals(1, localCleared)
        assertEquals(1, changed)
        assertEquals("pending", marker.text)
        assertEquals(1, logged.size)
        // The record is still stored, but the phone does not use it.
        assertNull(store.load())
    }

    @Test
    fun aClearThatFailedIsRetriedAtTheNextStart() {
        delegate.failClear = true
        store().clear()
        assertEquals("pending", marker.text)

        // Next start: a new store object over the same marker; the delegate now works.
        delegate.failClear = false
        val restarted = store()
        assertTrue(restarted.retryPendingClear())

        assertNull(delegate.pairing)
        assertNull(marker.text)
        assertNull(restarted.load())
    }

    @Test
    fun theRetryKeepsTheMarkerWhileItStillFails() {
        delegate.failClear = true
        store().clear()
        val restarted = store()

        assertFalse(restarted.retryPendingClear())

        assertEquals("pending", marker.text)
        assertNull(restarted.load())
        assertTrue(delegate.pairing != null) // not forgotten: the next start tries again
    }

    @Test
    fun aNewPairingWaitsForThePendingClearAndIsNotWipedByItsRetry() {
        delegate.failClear = true
        val store = store()
        store.clear()

        try {
            store.save(PAIRING)
            fail("a pairing must not be saved next to a record that could not be removed")
        } catch (e: CompanionException) {
            assertEquals("previous_data_not_removed", e.code)
        }

        delegate.failClear = false
        store.save(PAIRING)
        assertEquals(PAIRING.token, store.load()?.token)
        assertNull(marker.text)
        assertTrue(store.retryPendingClear()) // nothing pending: the new pairing is not touched
        assertEquals(PAIRING.token, store.load()?.token)
    }

    @Test
    fun aFailingMarkerWriteIsLoggedAndTheInMemoryFlagStillHolds() {
        marker.failWrites = true
        delegate.failClear = true
        val store = store()

        store.clear()

        assertEquals(2, logged.size)
        assertNull(store.load())
    }

    @Test
    fun withoutAMarkerAFailedClearStillHoldsForTheRunningProcess() {
        delegate.failClear = true
        val store = store(marker = null)

        store.clear()

        assertNull(store.load())
        delegate.failClear = false
        assertTrue(store.retryPendingClear())
    }

    @Test
    fun aSuccessfulClearLeavesNoMarker() {
        val store = store()

        store.clear()

        assertNull(marker.text)
        assertTrue(logged.isEmpty())
        assertEquals(0, lost)
    }
}
