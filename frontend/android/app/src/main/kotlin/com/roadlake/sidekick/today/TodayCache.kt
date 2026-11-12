package com.roadlake.sidekick.today

import java.io.IOException

/**
 * The bounded native cache of Today that the widget and the app share. One snapshot, partitioned by the server it was
 * read from: a snapshot of another server (or of nothing) reads as empty. It is cleared when the pairing ends
 * (unpair, 401, a new pairing). Titles are the only content; see [TodayTask].
 */
class TodayCache(private val store: TextStore) {
    @Synchronized
    fun load(partition: String): TodaySnapshot? {
        val text = try {
            store.read()
        } catch (_: IOException) {
            return null // unreadable now reads as a cache miss; a read writes nothing
        }
        val snapshot = TodayCodec.decode(text)
        if (snapshot == null || snapshot.partition != partition) return null
        return snapshot
    }

    /** True when something is stored, whatever it holds (used to remove leftovers of a pairing that is gone). */
    @Synchronized
    fun hasData(): Boolean = try {
        store.read() != null
    } catch (_: IOException) {
        true
    }

    /** Keeps the snapshot; a disk failure leaves the previous one and is reported as false, never thrown. */
    @Synchronized
    fun save(snapshot: TodaySnapshot): Boolean = try {
        store.write(TodayCodec.encode(snapshot))
        true
    } catch (_: IOException) {
        false
    }

    @Synchronized
    fun clear() = store.delete()

    /** [clear] that proves the cache is gone: throws [java.io.IOException] when anything of it remains. */
    @Synchronized
    fun erase() = store.erase()
}
