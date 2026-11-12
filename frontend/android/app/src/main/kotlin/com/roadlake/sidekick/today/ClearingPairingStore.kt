package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.Pairing
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.companion.PairingLock
import com.roadlake.sidekick.companion.PairingStore
import com.roadlake.sidekick.companion.UnreadablePairingException
import java.io.IOException

/**
 * A [PairingStore] that ends the phone's local Today data whenever the pairing changes: the cache and the outbox
 * belong to one pairing. `clear()` is the single point every end of a pairing passes (unpair, a 401, a failed
 * save), and `save()` starts from nothing, so a new pairing never inherits titles or queued completions from the
 * one before. [changed] runs afterwards so the widget redraws (or reads Today for the new pairing).
 *
 * Both advance [generation] first, so background work that began under the old pairing is refused from then on
 * ([PairingGeneration]) and cannot write what it fetched into the pairing that follows.
 *
 * Removing the old pairing's data is a condition for the next pairing, not a best effort. [clearLocalData] must throw
 * when something of it could not be proven gone; together with the delegate's own [PairingStore.clear] (the stored
 * record and its Keystore key) that is the wipe. [save] runs the whole wipe again, whatever the state, and refuses the
 * pairing with [PREVIOUS_DATA_NOT_REMOVED] when it fails. [readyForPairing] lets the client ask before it spends the
 * pairing code; it runs the same full, verified wipe (not just a check of the marker, which data left by an older app
 * version does not have). The marker is cleared with proof too, before a new pairing is stored.
 *
 * Two storage failures take the same way out as an ordinary unpair:
 * - A stored pairing that cannot be read ([UnreadablePairingException]) runs [clear] and then [onLost] (the page shows the
 *   pairing form with "the connection has ended"), and reads as "not paired".
 * - A [clear] whose wipe fails does not leave a half-removed pairing: the phone is marked disconnected (in memory and, when
 *   a [marker] is given, on disk) before the wipe starts and stays so until a wipe succeeds. [load] answers "not paired"
 *   meanwhile; the wipe is retried at the next start ([retryPendingClear]), by [load], and before any new [save]. Because
 *   the marker is written first, a process that dies in the middle of a wipe finishes it at the next start.
 * [onFailure] gets a content-free message for the log.
 */
class ClearingPairingStore(
    private val delegate: PairingStore,
    private val clearLocalData: () -> Unit,
    private val changed: () -> Unit,
    private val generation: PairingGeneration,
    private val onLost: () -> Unit = {},
    private val onFailure: (String) -> Unit = {},
    private val marker: TextStore? = null,
) : PairingStore {
    private val stateLock = Any()

    // One wipe-and-flag transition at a time: a retry that started before a new pairing was stored must not run its delegate
    // clear after the save and delete the new record. Taken before stateLock; never held while [changed] or [onLost] run.
    private val wipeLock = Any()

    @Volatile
    private var disconnected: Boolean = readMarker()

    override fun load(): Pairing? {
        if (disconnected && !retryPendingClear()) return null
        return try {
            delegate.load()
        } catch (_: UnreadablePairingException) {
            onFailure("stored pairing unreadable; unpairing")
            clear()
            onLost()
            null
        }
    }

    /**
     * Finishes a wipe that failed or was interrupted. True when nothing is pending any more. Run at app start, and by
     * [load], [readyForPairing] and [save] while a wipe is pending.
     */
    fun retryPendingClear(): Boolean = synchronized(wipeLock) {
        if (!disconnected) return true
        if (!finishWipe()) {
            onFailure("pending pairing wipe failed again; staying disconnected")
            return false
        }
        true
    }

    /**
     * Asked by the client before it spends the pairing code. Under [PairingLock], the same lock the client holds while it
     * saves, it first checks that nothing is paired: a pairing that exists (made by a concurrent attempt, or by one that
     * finished since the client looked) is refused with `already_paired` and left untouched, so a second attempt, valid or
     * not, can never wipe a working pairing. Only then does it run the whole wipe and prove it, whether or not a marker
     * exists: data an older app version failed to remove has no marker.
     */
    override fun readyForPairing(): Boolean {
        val ready = PairingLock.atomically {
            // A pending wipe means the stored record (if any) is the old pairing's remains and is meant to go.
            if (!disconnected && storedPairingExists()) throw CompanionException("already_paired")
            generation.advance()
            synchronized(wipeLock) {
                markDisconnected()
                finishWipe()
            }
        }
        if (!ready) onFailure("previous pairing data could not be removed; pairing code not spent")
        // No [changed]: nothing is paired here, so the widget already shows "connect".
        return ready
    }

    /** True when a readable pairing is stored. An unreadable record is not a pairing: [load] unpairs it the same way. */
    private fun storedPairingExists(): Boolean = try {
        delegate.load() != null
    } catch (_: UnreadablePairingException) {
        false
    }

    override fun save(pairing: Pairing) {
        // The old pairing's record, key, cache, outbox and the rest must be proven gone before this one is stored; the wipe
        // is run in full here even when nothing is marked pending (a process that died mid-wipe, a stale key).
        generation.advance()
        synchronized(wipeLock) {
            markDisconnected()
            // The new record is stored only once the data is gone AND the marker is proven not to be pending: a marker
            // that stayed behind would wipe this pairing at the next start.
            if (!finishWipe()) {
                onFailure("previous pairing data could not be removed; new pairing refused")
                throw CompanionException(PREVIOUS_DATA_NOT_REMOVED)
            }
            try {
                delegate.save(pairing)
            } catch (e: CompanionException) {
                // Whatever the failed save left behind goes too, so the refusal does not leave a half pairing.
                markDisconnected()
                finishWipe()
                throw e
            }
        }
        changed()
    }

    /** A renewed token or new dates of the same pairing: nothing local is cleared, the widget is not disturbed. */
    override fun update(pairing: Pairing) = delegate.update(pairing)

    override fun clear() {
        generation.advance()
        // Written first: a process that dies during the wipe resumes it at the next start.
        synchronized(wipeLock) {
            markDisconnected()
            if (!finishWipe()) {
                onFailure("pairing could not be wiped; marked disconnected, retried at next start")
            }
        }
        changed()
    }

    /**
     * Removes the stored pairing (record and key) and every piece of local data of it. Every step is attempted; true only
     * when all of them are proven done. stateLock guards only the delegate, never [clearLocalData]: that takes locks of its own.
     */
    private fun wipe(): Boolean {
        val stored = synchronized(stateLock) {
            try {
                delegate.clear()
                true
            } catch (_: Exception) {
                false
            }
        }
        val local = try {
            clearLocalData()
            true
        } catch (_: Exception) {
            false
        }
        return stored && local
    }

    /** The wipe, then the marker proven not pending. True only when both are done; otherwise the phone stays disconnected. */
    private fun finishWipe(): Boolean = wipe() && clearMarker()

    private fun readMarker(): Boolean = try {
        marker?.read().let { it != null && it != MARKER_DONE }
    } catch (_: IOException) {
        true // unreadable marker: assume a clear is pending, the retry is harmless when nothing is stored
    }

    private fun markDisconnected() = synchronized(stateLock) {
        disconnected = true
        val store = marker ?: return@synchronized
        try {
            store.write(MARKER_PENDING)
        } catch (_: IOException) {
            onFailure("disconnect marker could not be updated")
        }
    }

    /**
     * Ends the disconnected state, but only on proof: the marker is erased, or (when erasing fails) overwritten with
     * [MARKER_DONE], which [readMarker] reads as not pending. If neither can be shown, the phone stays disconnected, so a
     * marker left behind can never delete a pairing made after it. Chosen over a generation-bound marker because the
     * pairing record belongs to the delegate and carries no generation to compare against at the next start.
     */
    private fun clearMarker(): Boolean = synchronized(stateLock) {
        val store = marker
        if (store != null) {
            val gone = try {
                store.erase()
                true
            } catch (_: IOException) {
                try {
                    store.write(MARKER_DONE)
                    store.read() == MARKER_DONE
                } catch (_: IOException) {
                    false
                }
            }
            if (!gone) {
                onFailure("disconnect marker could not be removed; staying disconnected")
                return@synchronized false
            }
        }
        disconnected = false
        true
    }
}

private const val MARKER_PENDING = "pending"
private const val MARKER_DONE = "done"

/** The closed error code of a pairing the phone refused because the previous pairing's data could not be removed. */
const val PREVIOUS_DATA_NOT_REMOVED = "previous_data_not_removed"

/**
 * Runs every step, also after one failed, and throws [IOException] when any did. For [ClearingPairingStore]'s
 * `clearLocalData`: a failure to remove one thing must not stop the others from being removed.
 */
fun runAllOrThrow(vararg steps: () -> Unit) {
    var failed = 0
    steps.forEach { step ->
        try {
            step()
        } catch (_: Exception) {
            failed++
        }
    }
    if (failed > 0) throw IOException("$failed local data step(s) failed")
}
