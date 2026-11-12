package com.roadlake.sidekick.companion

import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/**
 * Serialises every read-modify-write of the stored pairing: a renewal, a refresh of the device record, a pairing, a
 * clear. One phone holds one pairing, so one process-wide lock is the whole scope. Network calls are never made while it
 * is held, only the short load/check/store sequence, so a clear waits at most for one storage write and always runs
 * after any update that began first (a clear wins over a renewal that is in progress). Reentrant, so a store that calls
 * back into the client cannot deadlock itself.
 */
internal object PairingLock {
    private val lock = ReentrantLock()

    fun <T> atomically(block: () -> T): T = lock.withLock(block)
}
