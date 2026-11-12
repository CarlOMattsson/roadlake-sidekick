package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingStore
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Assert.fail
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.io.File
import java.io.IOException

private val OLD = Pairing("https://sidekick.example", "rsc_abcdefghijklmnopqrstuvwxyz0123456789", "Pixel", "2026-11-01T10:00:00Z")
private val NEW = Pairing("https://other.example", "rsc_zyxwvutsrqponmlkjihgfedcba9876543210", "Pixel", "2026-11-02T10:00:00Z")

/** The record and the Keystore key as one store: [stuck] makes the clear fail and leave the record in place. */
private class RecordStore(var pairing: Pairing? = null) : PairingStore {
    var stuck = false

    override fun load() = pairing

    override fun save(pairing: Pairing) {
        this.pairing = pairing
    }

    override fun clear() {
        if (stuck) throw CompanionException("secure_storage")
        pairing = null
    }
}

/**
 * The wipe is a condition for the next pairing: real files stand for the cache, the outbox and the disconnect marker,
 * and a non-empty directory where the `.corrupt` copy belongs makes the removal of one store impossible, as a failing
 * disk would. A "restart" is a new [ClearingPairingStore] over the same files and the same record.
 */
class PairingWipeTest {
    @get:Rule
    val folder = TemporaryFolder()

    private val record = RecordStore(OLD)
    private val generation = PairingGeneration()
    private val logged = mutableListOf<String>()
    private var changed = 0

    private fun file(name: String) = File(folder.root, "today/$name")

    private fun textStore(name: String) = FileTextStore(file(name), syncDirectory = {})

    private val cacheStore get() = textStore("today-cache.json")
    private val outboxStore get() = textStore("outbox.json")

    private fun cache() = TodayCache(cacheStore)

    private fun outbox() = Outbox(outboxStore) { 1_000L }

    /** A pairing store as the app wires it: the cache and the outbox are erased with proof. */
    private fun store(crashDuringWipe: Boolean = false) = ClearingPairingStore(
        record,
        clearLocalData = {
            if (crashDuringWipe) throw OutOfMemoryError("process died") // not an Exception: nothing catches it
            runAllOrThrow(cache()::erase, outbox()::erase)
        },
        changed = { changed++ },
        generation = generation,
        onFailure = { logged += it },
        marker = textStore("pairing-disconnected"),
    )

    private fun fillOldPairingData() {
        cacheStore.write("""{"titles":["Call the dentist"]}""")
        outboxStore.write("""[{"task":"t1"}]""")
    }

    /** Makes the cache's copy impossible to remove, like a disk that refuses. */
    private fun jamCache() {
        val corrupt = File(file("today-cache.json").path + ".corrupt")
        corrupt.mkdirs()
        File(corrupt, "inner").writeText("x")
    }

    private fun cacheLeftover() = File(file("today-cache.json").path + ".corrupt").exists()

    private fun unjamCache() {
        File(file("today-cache.json").path + ".corrupt").deleteRecursively()
    }

    private fun assertRefused(block: () -> Unit) {
        try {
            block()
            fail("the new pairing must be refused")
        } catch (e: CompanionException) {
            assertEquals("previous_data_not_removed", e.code)
        }
    }

    @Test
    fun aNewPairingIsRefusedWhileAnOldCacheOrOutboxRemains() {
        fillOldPairingData()
        jamCache()
        val store = store()

        store.clear() // the unpair: the outbox goes, the cache's quarantined copy cannot
        assertTrue(cacheLeftover())
        assertFalse(outbox().hasData())
        assertNull(store.load()) // reads as not paired while the wipe is pending

        assertRefused { store.save(NEW) }

        assertNull(record.pairing) // nothing of the new pairing was stored
        assertTrue(cacheLeftover()) // the leftover is still reported, not forgotten
        assertEquals(1, changed) // the widget was told of the unpair only
        assertTrue(logged.any { it.contains("new pairing refused") })
        assertTrue(logged.none { it.contains("rsc_") || it.contains("Call the dentist") })
    }

    @Test
    fun theRefusedPairingSucceedsOnceTheDataCouldBeRemoved() {
        fillOldPairingData()
        jamCache()
        val store = store()
        store.clear()
        assertRefused { store.save(NEW) }

        unjamCache()
        store.save(NEW)

        assertEquals(NEW.token, store.load()?.token)
        assertFalse(cache().hasData())
        assertFalse(outbox().hasData())
        assertFalse(file("pairing-disconnected").exists())
        assertFalse(file("today-cache.json").exists())
    }

    @Test
    fun aRecordThatCannotBeRemovedAlsoRefusesTheNewPairing() {
        fillOldPairingData()
        record.stuck = true
        val store = store()
        store.clear()

        assertFalse(cache().hasData()) // the local data went anyway
        assertRefused { store.save(NEW) }
        assertEquals(OLD.token, record.pairing?.token) // the old record is still the only one

        record.stuck = false
        store.save(NEW)
        assertEquals(NEW.token, store.load()?.token)
    }

    @Test
    fun aProcessThatDiedMidWipeFinishesTheWipeAtTheNextStart() {
        fillOldPairingData()
        try {
            store(crashDuringWipe = true).clear()
            fail("the simulated crash must propagate")
        } catch (_: OutOfMemoryError) {
        }
        // On disk: the marker (written first) and the old data; in the record: already gone or still there.
        assertTrue(file("pairing-disconnected").exists())
        assertTrue(cache().hasData())

        val restarted = store() // new process, same files
        assertNull(restarted.load()) // not paired, even though the record is still there
        assertTrue(restarted.retryPendingClear())

        assertNull(record.pairing)
        assertFalse(cache().hasData())
        assertFalse(outbox().hasData())
        assertFalse(file("pairing-disconnected").exists())
    }

    @Test
    fun aRestartWhileTheDataStillCannotBeRemovedStaysDisconnectedAndRefuses() {
        fillOldPairingData()
        jamCache()
        store().clear()

        val restarted = store()
        assertFalse(restarted.retryPendingClear())
        assertNull(restarted.load())
        assertRefused { restarted.save(NEW) }
        assertTrue(file("pairing-disconnected").exists())
    }

    @Test
    fun aNewPairingWipesLeftoversEvenWhenNothingWasMarkedPending() {
        // A process that died after the marker was lost, or a record that survived a restore: save does not trust the flag.
        fillOldPairingData()
        val store = store()
        val before = generation.current()

        store.save(NEW)

        assertEquals(NEW.token, record.pairing?.token)
        assertFalse(cache().hasData())
        assertFalse(outbox().hasData())
        assertTrue(generation.current() > before)
        assertFalse(file("pairing-disconnected").exists())
        assertEquals(1, changed)
    }

    @Test
    fun theClientRefusesBeforeSpendingThePairingCode() {
        fillOldPairingData()
        jamCache()
        val clearing = store()
        clearing.clear()
        val http = ScriptedHttp()
        val client = CompanionClient(clearing, http, allowLocalCleartext = false, generation = generation)

        try {
            client.pair("https://sidekick.example", "abcdefghijklmnop1234")
            fail("pairing must be refused")
        } catch (e: CompanionException) {
            assertEquals("previous_data_not_removed", e.code)
        }
        assertTrue(http.calls.isEmpty()) // the code was not sent, so it is still good

        unjamCache()
        assertTrue(clearing.readyForPairing())
    }

    @Test
    fun theClientWipesDataThatHasNoMarkerBeforeSpendingTheCode() {
        // Left by an older app version: no marker, and the data cannot be removed.
        record.pairing = null // the record is gone; only the data an older version could not remove is left
        fillOldPairingData()
        jamCache()
        val clearing = store()
        assertFalse(file("pairing-disconnected").exists())
        val http = ScriptedHttp()
        val client = CompanionClient(clearing, http, allowLocalCleartext = false, generation = generation)

        try {
            client.pair("https://sidekick.example", "abcdefghijklmnop1234")
            fail("pairing must be refused")
        } catch (e: CompanionException) {
            assertEquals("previous_data_not_removed", e.code)
        }
        assertTrue(http.calls.isEmpty()) // the code is still good
        assertFalse(outbox().hasData()) // the wipe ran, not just a marker check
        assertNull(clearing.load())

        unjamCache()
        assertTrue(clearing.readyForPairing())
        assertFalse(cache().hasData())
    }

    /** A marker whose removal fails: delete does nothing, erase throws; overwriting works. */
    private class StubbornMarker(val inner: MemoryTextStore = MemoryTextStore()) : TextStore by inner {
        override fun delete() {}

        override fun erase() = throw IOException("still present after delete")
    }

    private fun storeWith(marker: TextStore) = ClearingPairingStore(
        record,
        clearLocalData = { runAllOrThrow(cache()::erase, outbox()::erase) },
        changed = { changed++ },
        generation = generation,
        onFailure = { logged += it },
        marker = marker,
    )

    @Test
    fun aMarkerThatCannotBeDeletedNeverWipesTheNewPairingAtTheNextStart() {
        val marker = StubbornMarker()
        storeWith(marker).save(NEW) // the delete fails, the overwrite works: stored, marker no longer pending
        assertEquals(NEW.token, record.pairing?.token)

        val restarted = storeWith(marker)
        assertEquals(NEW.token, restarted.load()?.token)
        assertTrue(restarted.retryPendingClear())
        assertEquals(NEW.token, record.pairing?.token)
    }

    @Test
    fun aMarkerThatCanNeitherBeRemovedNorOverwrittenRefusesThePairing() {
        val marker = StubbornMarker()
        // The pending marker can be written once; after that nothing can change it.
        val locked = object : TextStore by marker {
            override fun write(text: String) {
                if (marker.inner.text != null) throw IOException("read-only")
                marker.write(text)
            }
        }
        val store = storeWith(locked)

        assertRefused { store.save(NEW) }

        assertNull(record.pairing) // nothing was stored that the marker could later delete
        assertNull(store.load()) // and the phone stays disconnected
        assertFalse(store.readyForPairing())
        assertEquals("pending", marker.inner.text)
    }

    @Test
    fun eraseRemovesEverythingAndThrowsWhenSomethingRemains() {
        val store = textStore("state.json")
        store.write("secret")
        store.erase()
        assertFalse(file("state.json").exists())

        store.write("secret")
        val corrupt = File(file("state.json").path + ".corrupt")
        corrupt.mkdirs()
        File(corrupt, "inner").writeText("x")
        try {
            store.erase()
            fail("a copy that remains must be reported")
        } catch (_: IOException) {
        }
        assertFalse(file("state.json").exists()) // the other files are still removed
    }

    @Test
    fun runAllOrThrowRunsEveryStepAndReportsAFailure() {
        var ran = 0
        try {
            runAllOrThrow({ ran++ }, { throw IOException("x") }, { ran++ })
            fail("a failed step must be reported")
        } catch (_: IOException) {
        }
        assertEquals(2, ran)
    }
}
