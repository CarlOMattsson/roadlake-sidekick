package com.roadlake.sidekick.companion

import java.util.concurrent.atomic.AtomicLong

/**
 * Which pairing a piece of background work belongs to. The number changes at every start and end of a pairing (see
 * [com.roadlake.sidekick.today.ClearingPairingStore]); work that began under an earlier number must not write to, or
 * send with the credential of, a later pairing: a late answer from the old server would otherwise be stored as the new
 * pairing's Today, acknowledged, registered or counted as its renewal.
 *
 * A unit of work reads [current] first (before it loads the pairing), runs its network calls inside [pinned], and does
 * every write to local state through [runIfCurrent]. The check and the write are one step under [PairingLock], the lock
 * every pairing change holds, so a change cannot slip in between and be undone by the write.
 */
class PairingGeneration {
    private val value = AtomicLong()
    private val pin = ThreadLocal<Long?>()

    fun current(): Long = value.get()

    /** A pairing started or ended. Called under [PairingLock], before the local data of the old pairing is cleared. */
    fun advance() {
        value.incrementAndGet()
    }

    /** Runs [write] only while [captured] is still the current generation; false (and nothing run) when it is not. */
    fun runIfCurrent(captured: Long, write: () -> Unit): Boolean = PairingLock.atomically {
        if (value.get() == captured) {
            write()
            true
        } else {
            false
        }
    }

    /**
     * Runs [block] (on this thread) so that every request [CompanionClient] makes in it fails with `not_paired` once the
     * generation is no longer [captured]: the old work never sends under the credential of a later pairing.
     */
    fun <T> pinned(captured: Long, block: () -> T): T {
        val outer = pin.get()
        pin.set(captured)
        try {
            return block()
        } finally {
            if (outer == null) pin.remove() else pin.set(outer)
        }
    }

    /**
     * For a call that is handed to another thread (a pool) and may wait there: fixes the pairing it belongs to now, on
     * the caller's thread, not when a pool thread gets to it. The returned task runs [work] (given that generation)
     * [pinned] to it, so a call made before an unpair and a new pairing is refused with `not_paired` instead of being
     * sent with the new pairing's credential.
     */
    fun <T> bindNow(work: (Long) -> T): () -> T {
        val captured = current()
        return { pinned(captured) { work(captured) } }
    }

    /** For [CompanionClient]: called after the pairing was loaded, before the request is built. */
    internal fun checkPinned() {
        val captured = pin.get() ?: return
        if (captured != value.get()) throw CompanionException("not_paired", beforeSend = true)
    }
}
