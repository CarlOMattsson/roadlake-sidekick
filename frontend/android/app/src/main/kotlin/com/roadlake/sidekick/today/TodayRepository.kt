package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.PairingGeneration
import java.util.UUID
import java.util.concurrent.locks.ReentrantLock
import kotlin.concurrent.withLock

/** What the widget draws. */
sealed interface TodayState {
    /** No pairing: the widget asks the user to connect in the app. */
    data object NotPaired : TodayState

    /** Paired, but Today has not been read yet. */
    data object Loading : TodayState

    /**
     * [pendingTaskIds] are the rows whose completion is queued and not yet confirmed by the server. [undoTaskIds] are those
     * of them still inside their undo window: not sent yet, and [TodayRepository.undoCompletion] takes them back.
     */
    class Ready(val snapshot: TodaySnapshot, val pendingTaskIds: Set<String>, val undoTaskIds: Set<String> = emptySet()) : TodayState
}

enum class EnqueueResult { QUEUED, UNKNOWN_TASK, NOT_PAIRED, STORAGE_FAILED }

/** How queueing a shopping write (a purchase or an added item) ended, and the entry that is queued when it is [EnqueueResult.QUEUED]. */
class QueuedWrite(val result: EnqueueResult, val entry: OutboxEntry?)

/** How a [TodayRepository.sync] ended; [RETRY] asks the scheduler to try again later, with back-off. */
enum class SyncResult { UPDATED, NOT_PAIRED, RETRY }

/**
 * The widget's and the app's shared Today: the cache, the outbox of completions and the two requests to the server
 * (read Today, complete a Task). The outbox also holds the shopping room's purchases and added items made without a
 * network; they are queued here ([enqueuePurchase], [enqueueShoppingAdd]) and sent by the same drain, in the order they were made, with the same rules. It owns the rules; the Glance widget and the WorkManager workers only call it. It is
 * free of Android types so it is unit tested on the JVM.
 *
 * - The server is authoritative. A completion is sent with the version the row had and the key made at the tap, and
 *   again with the same key until the server answers finally. A 409 (the Task changed elsewhere) removes the row and
 *   reads Today again: the user sees the current state and decides; the widget never re-sends with a newer version.
 * - Pending is shown from the outbox, never invented: a row is pending exactly while its entry is queued.
 * - A 401 or a missing pairing clears the cache and the outbox. Nothing is left that belongs to a pairing that is gone.
 * - Reads and drains run one at a time ([sync]); enqueueing only touches the outbox and returns at once, so a tap never
 *   waits for the network.
 * - Work belongs to the pairing it began under ([PairingGeneration]): its requests are pinned to it and every write to the
 *   cache or the outbox is made only while that pairing is still the current one. An answer that arrives after an unpair
 *   or a new pairing is dropped, and the rest of a drain is not sent with the new credential.
 */
class TodayRepository(
    private val client: CompanionClient,
    private val cache: TodayCache,
    private val outbox: Outbox,
    private val clock: () -> Long,
    private val newKey: () -> String = { "widget-" + UUID.randomUUID() },
    private val generation: PairingGeneration = PairingGeneration(),
) {
    private val syncLock = ReentrantLock()

    fun state(): TodayState {
        val captured = generation.current()
        val status = client.status()
        if (!status.paired) {
            if (cache.hasData() || outbox.hasData()) clearAllIfCurrent(captured)
            return TodayState.NotPaired
        }
        val partition = partitionOf(status.serverHost)
        val snapshot = cache.load(partition) ?: return TodayState.Loading
        val queued = pendingOf(OutboxKind.TASK_COMPLETION)
        val now = clock()
        return TodayState.Ready(
            snapshot,
            queued.mapTo(HashSet()) { it.subjectId },
            queued.filter { it.isHeld(now) }.mapTo(HashSet()) { it.subjectId },
        )
    }

    /**
     * Queues the completion of a row of the cached Today. Returns before any network call. With a [holdMillis] the entry
     * is queued but not sent until then (the widget's undo window, [UNDO_WINDOW_MILLIS]); [undoCompletion] takes it back.
     */
    fun enqueueCompletion(taskId: String, holdMillis: Long = 0L): EnqueueResult {
        val captured = generation.current()
        val status = client.status()
        if (!status.paired) return EnqueueResult.NOT_PAIRED
        val row = cache.load(partitionOf(status.serverHost))?.tasks?.firstOrNull { it.id == taskId }
            ?: return EnqueueResult.UNKNOWN_TASK
        // A row of the old pairing's Today must not be queued once the pairing has changed: it would go to the new server.
        var queued = false
        val current = generation.runIfCurrent(captured) { queued = outbox.enqueue(row.id, row.version, newKey(), holdMillis) != null }
        return when {
            !current -> EnqueueResult.NOT_PAIRED
            queued -> EnqueueResult.QUEUED
            else -> EnqueueResult.STORAGE_FAILED
        }
    }

    /**
     * Takes back a completion that is still inside its undo window: it leaves the queue unsent, so no request is made and
     * nothing has to be re-opened on the server. False when the window has ended (the completion is, or is about to be,
     * sent) or when there is nothing to take back.
     */
    fun undoCompletion(taskId: String): Boolean {
        val captured = generation.current()
        if (!client.status().paired) return false
        var undone = false
        generation.runIfCurrent(captured) { undone = outbox.undoHeld(taskId) }
        return undone
    }

    /** When the earliest held completion may be sent, or null when none is held: the time a sync must come back. */
    fun nextSendAtMillis(): Long? = if (client.status().paired) outbox.nextSendAtMillis() else null

    /**
     * Queues a shopping purchase the page could not send (no network, or no answer): the item, the version it was
     * written against, the asked state and the page's own idempotency key, which the first attempt already carried, so
     * the server replays rather than repeats a write it did receive. Returns at once; [sync] sends it. [queuedPurchase]
     * is the entry that is queued (an earlier one for the same item wins).
     *
     * [underGeneration] is the pairing the failed attempt began under ([pairingGeneration], read when that request
     * started), not the one at this moment: a late network error after an unpair and a new pairing must not put the
     * old pairing's purchase in the new pairing's queue.
     */
    fun enqueuePurchase(underGeneration: Long, itemId: String, version: Int, purchased: Boolean, idempotencyKey: String): QueuedWrite {
        val captured = underGeneration
        if (!client.status().paired) return QueuedWrite(EnqueueResult.NOT_PAIRED, null)
        var entry: OutboxEntry? = null
        val current = generation.runIfCurrent(captured) {
            entry = outbox.enqueuePurchase(itemId, version, purchased, idempotencyKey)
        }
        return when {
            !current -> QueuedWrite(EnqueueResult.NOT_PAIRED, null)
            entry != null -> QueuedWrite(EnqueueResult.QUEUED, entry)
            else -> QueuedWrite(EnqueueResult.STORAGE_FAILED, null)
        }
    }

    /**
     * Queues items the page could not add (no network, or no answer): the list, the request body it built
     * (`{ items, merge_duplicates }`) and the key its first attempt carried, so the server replays rather than repeats an
     * add it did receive. [underGeneration] binds it to the pairing the failed attempt began under, as for
     * [enqueuePurchase]. The same key queued twice is one add.
     */
    fun enqueueShoppingAdd(underGeneration: Long, listId: String, bodyJson: String, idempotencyKey: String): QueuedWrite {
        if (!client.status().paired) return QueuedWrite(EnqueueResult.NOT_PAIRED, null)
        var entry: OutboxEntry? = null
        val current = generation.runIfCurrent(underGeneration) {
            entry = outbox.enqueueShoppingAdd(listId, bodyJson, idempotencyKey)
        }
        return when {
            !current -> QueuedWrite(EnqueueResult.NOT_PAIRED, null)
            entry != null -> QueuedWrite(EnqueueResult.QUEUED, entry)
            else -> QueuedWrite(EnqueueResult.STORAGE_FAILED, null)
        }
    }

    /** The pairing generation now; a request reads it before it starts so that a later [enqueuePurchase] can be bound to it. */
    fun pairingGeneration(): Long = generation.current()

    /** The purchases waiting to be sent, oldest first. Empty without a pairing. */
    fun queuedPurchases(): List<OutboxEntry> = if (client.status().paired) pendingOf(OutboxKind.SHOPPING_PURCHASE) else emptyList()

    /** The added items waiting to be sent, oldest first. Empty without a pairing. */
    fun queuedShoppingAdds(): List<OutboxEntry> = if (client.status().paired) pendingOf(OutboxKind.SHOPPING_ADD) else emptyList()

    /** The Task completions waiting to be sent (from the widget or the app), oldest first. */
    fun queuedCompletions(): List<OutboxEntry> = pendingOf(OutboxKind.TASK_COMPLETION)

    /** The shopping writes that failed (expired or refused) and wait for the user, oldest first. Empty without a pairing. */
    fun failedShoppingWrites(): List<OutboxEntry> =
        if (client.status().paired) outbox.failed().filter { it.kind != OutboxKind.TASK_COMPLETION } else emptyList()

    /** Whether a failed write may be sent again: its key is still within the server's idempotency window. Otherwise it can only be removed. */
    fun canRetryFailedWrite(entry: OutboxEntry): Boolean = entry.keyStillSafe(clock())

    /** Puts a failed write back in the queue under its own key. False when there is no such failed write or it could not be saved. */
    fun retryFailedWrite(idempotencyKey: String): Boolean = client.status().paired && outbox.retryFailed(idempotencyKey)

    /** Removes a failed write for good. */
    fun discardFailedWrite(idempotencyKey: String): Boolean = client.status().paired && outbox.discardFailed(idempotencyKey)

    private fun pendingOf(kind: OutboxKind) = outbox.pending().filter { it.kind == kind }

    /** True when there is a write to send. */
    fun hasPending(): Boolean = outbox.pending().isNotEmpty()

    /** Sends the queued completions, then reads Today again. The one entry point of the workers. */
    fun sync(): SyncResult = syncLock.withLock {
        // Read before anything else: the work is tied to the pairing that exists now, and to no later one.
        val captured = generation.current()
        generation.pinned(captured) {
            val drained = drain(captured)
            if (drained.pairingLost) return@pinned SyncResult.NOT_PAIRED
            val fetched = fetch(captured, drained.notice)
            // The expired count stays until a read has stored the notice, so a failed read tells the user on the next run.
            if (fetched == SyncResult.UPDATED && drained.expired) generation.runIfCurrent(captured) { outbox.clearExpired() }
            when {
                fetched == SyncResult.NOT_PAIRED -> SyncResult.NOT_PAIRED
                fetched == SyncResult.RETRY || drained.retryLater -> SyncResult.RETRY
                else -> SyncResult.UPDATED
            }
        }
    }

    /** Like [sync] but does nothing when Today was read less than [maxAgeMillis] ago and nothing is queued. */
    fun syncIfStale(maxAgeMillis: Long): SyncResult? {
        val status = client.status()
        if (status.paired && !hasPending() && outbox.expiredCount() == 0) {
            val snapshot = cache.load(partitionOf(status.serverHost))
            if (snapshot != null && clock() - snapshot.syncedAtMillis in 0 until maxAgeMillis) return null
        }
        return sync()
    }

    /** Ends everything this phone keeps of Today. */
    fun clearAll() {
        cache.clear()
        outbox.clear()
    }

    /** Like [clearAll], but only while [captured] is the current pairing: a new pairing's data is not ours to delete. */
    private fun clearAllIfCurrent(captured: Long) {
        generation.runIfCurrent(captured, ::clearAll)
    }

    /** A drain that began under a pairing that has ended or been replaced: its answers belong to nobody. */
    private fun endedPairing() = Drain(null, retryLater = false, pairingLost = true)

    private class Drain(val notice: TodayNotice?, val retryLater: Boolean, val pairingLost: Boolean, val expired: Boolean = false)

    private fun drain(captured: Long): Drain {
        // A completion still in its undo window is queued but not sent: the Undo of the widget may yet take it back.
        val queued = outbox.pending().filterNot { it.isHeld(clock()) }
        // Completions dropped for age are told to the user, unless a final answer below has something more specific to say.
        val expired = outbox.expiredCount() > 0
        var notice: TodayNotice? = if (expired) TodayNotice.EXPIRED else null
        for (entry in queued) {
            val result = try {
                client.request(
                    method = "POST",
                    path = entry.path,
                    query = null,
                    bodyJson = entry.bodyJson(),
                    idempotencyKey = entry.idempotencyKey,
                )
            } catch (e: CompanionException) {
                if (e.code == "not_paired") {
                    clearAllIfCurrent(captured)
                    return endedPairing()
                }
                if (e.code in REFUSED_BEFORE_SEND) {
                    // The request itself was refused on the phone: it can never be sent, so it must not hold up the queue.
                    if (!generation.runIfCurrent(captured) { settle(entry) }) return endedPairing()
                    continue
                }
                if (!generation.runIfCurrent(captured) { outbox.recordAttempt(entry.subjectId, entry.idempotencyKey) }) {
                    return endedPairing()
                }
                return Drain(notice, retryLater = true, pairingLost = false, expired = expired)
            }
            when {
                result.status in 200..299 -> {
                    if (!generation.runIfCurrent(captured) { finish(entry) }) return endedPairing()
                }

                result.status == 401 -> {
                    // The client has already removed the pairing, which cleared the cache and the outbox.
                    clearAllIfCurrent(captured)
                    return endedPairing()
                }

                result.status == 408 || result.status == 429 || result.status >= 500 -> {
                    if (!generation.runIfCurrent(captured) { outbox.recordAttempt(entry.subjectId, entry.idempotencyKey) }) {
                        return endedPairing()
                    }
                    return Drain(notice, retryLater = true, pairingLost = false, expired = expired)
                }

                else -> {
                    // 409 (changed elsewhere), 404/410 (gone) and the other refusals are final: no automatic rebase.
                    if (!generation.runIfCurrent(captured) { settle(entry) }) return endedPairing()
                    // A shopping write has no row in Today: it stays in the outbox as failed, and the app tells the user.
                    if (entry.kind != OutboxKind.TASK_COMPLETION) continue
                    val outcome = if (result.status == 409 || result.status == 404 || result.status == 410) {
                        TodayNotice.CONFLICT
                    } else {
                        TodayNotice.REJECTED
                    }
                    if (notice != TodayNotice.CONFLICT) notice = outcome
                }
            }
        }
        return Drain(notice, retryLater = false, pairingLost = false, expired = expired)
    }

    /** The server has answered finally: the entry leaves the outbox and a completed Task's row leaves the cached Today. */
    private fun finish(entry: OutboxEntry) {
        outbox.remove(entry.subjectId, entry.idempotencyKey)
        if (entry.kind == OutboxKind.TASK_COMPLETION) dropRow(entry.subjectId)
    }

    /** A final refusal: a task completion leaves the queue (the widget's notice tells it); a shopping write stays as failed, for the user to retry or remove. */
    private fun settle(entry: OutboxEntry) {
        if (entry.kind == OutboxKind.TASK_COMPLETION) finish(entry) else outbox.markRejected(entry.subjectId, entry.idempotencyKey)
    }

    private fun fetch(captured: Long, notice: TodayNotice?): SyncResult {
        val status = client.status()
        if (!status.paired) return SyncResult.NOT_PAIRED
        val partition = partitionOf(status.serverHost)
        val response = try {
            client.request("GET", TODAY_PATH, TODAY_QUERY, null, null)
        } catch (e: CompanionException) {
            if (e.code == "not_paired") {
                clearAllIfCurrent(captured)
                return SyncResult.NOT_PAIRED
            }
            keepFailure(captured, partition, notice)
            return SyncResult.RETRY
        }
        if (response.status == 401) {
            clearAllIfCurrent(captured)
            return SyncResult.NOT_PAIRED
        }
        if (response.status != 200) {
            keepFailure(captured, partition, notice)
            return SyncResult.RETRY
        }
        val fresh = try {
            TodayCodec.fromToday(response.body, partition, clock())
        } catch (_: CompanionException) {
            keepFailure(captured, partition, notice)
            return SyncResult.RETRY
        }
        // Dropped when the pairing changed while the answer was on its way; the new pairing reads Today for itself.
        var written = false
        val current = generation.runIfCurrent(captured) {
            written = cache.save(fresh.withNotice(notice))
        }
        // A cache that could not be written is a failed run (the widget still shows the old list), so WorkManager retries.
        return when {
            !current -> SyncResult.NOT_PAIRED
            written -> SyncResult.UPDATED
            else -> SyncResult.RETRY
        }
    }

    /**
     * A read that failed still shows the user what the failed completion did to the list, and that the list is as old as
     * its sync time says ([TodaySnapshot.offline]).
     */
    private fun keepFailure(captured: Long, partition: String, notice: TodayNotice?) {
        generation.runIfCurrent(captured) {
            cache.load(partition)?.let {
                cache.save(
                    it.withOffline(true).let { kept ->
                        if (notice !=
                            null
                        ) {
                            kept.withNotice(notice)
                        } else {
                            kept
                        }
                    },
                )
            }
        }
    }

    /**
     * A refresh found no network at all, so no request was made: the cached Today is marked as offline so the widget says
     * so instead of staying silent. The next read that gets through clears it.
     */
    fun markOffline() {
        val captured = generation.current()
        val status = client.status()
        if (!status.paired) return
        val partition = partitionOf(status.serverHost)
        generation.runIfCurrent(captured) { cache.load(partition)?.let { if (!it.offline) cache.save(it.withOffline(true)) } }
    }

    private fun dropRow(taskId: String) {
        val status = client.status()
        if (!status.paired) return
        val partition = partitionOf(status.serverHost)
        cache.load(partition)?.let { cache.save(it.without(taskId)) }
    }

    /** The cache belongs to one server: its host as the pairing reports it. */
    private fun partitionOf(serverHost: String?): String = serverHost ?: ""

    companion object {
        /** How long a ticked row waits in the widget for Undo before its completion may be sent. */
        const val UNDO_WINDOW_MILLIS = 5_000L

        /** Refusals of the phone's own request policy: the entry can never be sent as it is. */
        private val REFUSED_BEFORE_SEND = setOf("bad_request", "path_refused")

        private const val TODAY_PATH = "/companion/v1/work/today"

        // The server chooses and counts Today's rows (overdue first); the client only bounds how many it keeps.
        private val TODAY_QUERY: Map<String, List<String>> = mapOf("limit" to listOf(TodaySnapshot.MAX_TASKS.toString()))
    }
}
