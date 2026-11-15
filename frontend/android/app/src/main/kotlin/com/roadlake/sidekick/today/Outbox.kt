package com.roadlake.sidekick.today

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

/**
 * What a queued write does. The wire name is what the file stores (and what the page calls it; the record writes are named
 * after the tool the room called); an entry without one is a [TASK_COMPLETION]. A [keyed] kind has no row yet, so one
 * write is told from another by its key. A kind that [sendsPayload] sends the request body the page built, as it is.
 * A kind that [mergesEdits] may take a second edit of the same row into the one still waiting to be sent.
 */
enum class OutboxKind(val wire: String, val keyed: Boolean = false, val sendsPayload: Boolean = false, val mergesEdits: Boolean = false) {
    /** The widget's (and the app's) tick of a Task: `POST /companion/v1/tasks/{id}/complete`. */
    TASK_COMPLETION("task"),

    /** A shopping item bought or put back in a shop without coverage: `POST /companion/v1/shopping/items/{id}/purchased`. */
    SHOPPING_PURCHASE("purchase"),

    /** A new shopping item (or a few) added without coverage: `POST /companion/v1/shopping/lists/{id}/items`. */
    SHOPPING_ADD("add", keyed = true, sendsPayload = true),

    /** A new Task made without coverage: `POST /companion/v1/tasks`. */
    TASK_CREATE("create_task", keyed = true, sendsPayload = true),

    /** An edit of a Task (title, note, due date, place, priority) made without coverage: `POST /companion/v1/tasks/{id}/update`. */
    TASK_EDIT("update_task", sendsPayload = true, mergesEdits = true),

    /** An edit of a Project made without coverage: `POST /companion/v1/projects/{id}/update`. */
    PROJECT_EDIT("update_project", sendsPayload = true, mergesEdits = true),

    /** A new journal entry written without coverage: `POST /companion/v1/journal/entries`. Held only in the encrypted journal queue. */
    JOURNAL_CREATE("write_journal_entry", keyed = true, sendsPayload = true),

    /** An edit of a journal entry made without coverage: `POST /companion/v1/journal/entries/{id}/update`. Held only in the encrypted journal queue. */
    JOURNAL_EDIT("update_journal_entry", sendsPayload = true),
    ;

    /** Whether the write is what the user wrote in the journal: held only in the encrypted journal queue, never in the outbox. */
    val isJournal: Boolean get() = this == JOURNAL_CREATE || this == JOURNAL_EDIT

    companion object {
        fun ofWire(wire: String?): OutboxKind? = if (wire == null) TASK_COMPLETION else entries.firstOrNull { it.wire == wire }
    }
}

/**
 * Why a write is no longer sent but kept for the user to see: it grew older than [Outbox.MAX_AGE_MILLIS]
 * ([EXPIRED]), or the server refused it for good ([REJECTED]: changed elsewhere, gone, not valid). The wire name is
 * what the file stores.
 */
enum class OutboxFailure(val wire: String) {
    EXPIRED("expired"),
    REJECTED("rejected"),
    ;

    companion object {
        fun ofWire(wire: String): OutboxFailure? = entries.firstOrNull { it.wire == wire }
    }
}

/**
 * One write the phone owes the server: what it does ([kind]) to which row ([subjectId], a Task or a shopping item), at
 * which version, under which idempotency key. The key is made once, when the user taps, and every retry of this entry
 * sends the same key and the same version, so a request whose answer was lost is replayed by the server, not applied
 * twice. [purchased] is the state a [OutboxKind.SHOPPING_PURCHASE] asks for (unused for a Task). For a
 * [OutboxKind.SHOPPING_ADD] the [subjectId] is the list and [payload] is the request body the page built
 * (`{ items, merge_duplicates }`), sent as it is; its [version] is unused (0). The record writes (a new or edited Task,
 * Project or journal entry) keep the body the page built in [payload] too: for an edit the [subjectId] is the row and
 * the [version] the one the edit rests on (it is in the body as well), for a creation the [subjectId] is [Outbox.NEW_SUBJECT].
 * A write other than a completion with a [failure] is never sent again by the drain: it waits for the user to retry or
 * remove it. [issuedAtMillis] is when the key was
 * made; unlike [createdAtMillis] it is not renewed by a retry, because the server forgets a key after its idempotency
 * window ([Outbox.MAX_KEY_AGE_MILLIS]) and an older key would make a re-sent write a new one. An entry with a
 * [notBeforeMillis] in the future is [isHeld]: it is queued (and shown as queued) but the drain does not send it yet,
 * and the widget's Undo ([Outbox.undoHeld]) can still take it back; so Undo never has to undo a request.
 */
class OutboxEntry(
    val subjectId: String,
    val version: Int,
    val idempotencyKey: String,
    val createdAtMillis: Long,
    val attempts: Int = 0,
    val kind: OutboxKind = OutboxKind.TASK_COMPLETION,
    val purchased: Boolean = false,
    val payload: String? = null,
    val failure: OutboxFailure? = null,
    val issuedAtMillis: Long = createdAtMillis,
    val notBeforeMillis: Long = 0L,
) {
    /** Whether the server can still be expected to recognise this entry's key, so that sending it again is a replay and never a second write. */
    fun keyStillSafe(nowMillis: Long): Boolean = nowMillis - issuedAtMillis <= Outbox.MAX_KEY_AGE_MILLIS

    /**
     * Whether the entry waits out its undo window at [nowMillis]: not sent, still takeable back. A hold is bounded
     * ([Outbox.MAX_HOLD_MILLIS]) and ends if the clock was set back before the entry was made, so a bad value in the file
     * can never keep a completion from being sent.
     */
    fun isHeld(nowMillis: Long): Boolean =
        nowMillis in createdAtMillis until notBeforeMillis && notBeforeMillis - createdAtMillis <= Outbox.MAX_HOLD_MILLIS

    /** The companion route the entry is sent to. */
    val path: String
        get() = when (kind) {
            OutboxKind.TASK_COMPLETION -> "/companion/v1/tasks/$subjectId/complete"
            OutboxKind.SHOPPING_PURCHASE -> "/companion/v1/shopping/items/$subjectId/purchased"
            OutboxKind.SHOPPING_ADD -> "/companion/v1/shopping/lists/$subjectId/items"
            OutboxKind.TASK_CREATE -> "/companion/v1/tasks"
            OutboxKind.TASK_EDIT -> "/companion/v1/tasks/$subjectId/update"
            OutboxKind.PROJECT_EDIT -> "/companion/v1/projects/$subjectId/update"
            OutboxKind.JOURNAL_CREATE -> "/companion/v1/journal/entries"
            OutboxKind.JOURNAL_EDIT -> "/companion/v1/journal/entries/$subjectId/update"
        }

    /** The JSON body of the request: the version, and for a purchase the asked state. */
    fun bodyJson(): String {
        if (kind.sendsPayload) return payload ?: "{}"
        val body = JSONObject().put("version", version)
        if (kind == OutboxKind.SHOPPING_PURCHASE) body.put("purchased", purchased)
        return body.toString()
    }

    internal fun withAttempt() = copy(attempts = attempts + 1)

    internal fun copy(
        createdAtMillis: Long = this.createdAtMillis,
        attempts: Int = this.attempts,
        failure: OutboxFailure? = this.failure,
    ) = OutboxEntry(
        subjectId, version, idempotencyKey, createdAtMillis, attempts, kind, purchased, payload, failure, issuedAtMillis, notBeforeMillis,
    )
}

/**
 * The phone's durable queue of reviewed writes (ADR-005: "a durable outbox only for reviewed task completion
 * commands"): the widget's task completions, and the shopping room's purchases made without a network. One queue, so
 * the widget and the app drain it in one place ([TodayRepository.sync]) with one credential and one back-off. It
 * survives a process kill and a reboot: every change is written before the call returns.
 * At most one entry per row and kind: a second tap on a row that is already pending does nothing, so a double tap is
 * one request with one key. An added item has no row yet, so an add is identified by its key instead: the same key is
 * the same add, a new key is a new one. An entry older than [MAX_AGE_MILLIS] is never applied long after the tap; a
 * dropped task completion is counted in the file ([expiredCount]) until [clearExpired], so the user is told that a
 * checked-off task was never sent. A shopping write that expires, or that the server refuses ([markRejected]), is not
 * dropped: it stays as a [failed] entry, out of [pending], until the user retries ([retryFailed]) or removes it
 * ([discardFailed]). Nothing the user queued disappears unseen. Failed entries count toward [MAX_ENTRIES].
 *
 * With [eraseWhenEmpty] a queue that becomes empty is not written as an empty file: its store is erased (an encrypted store
 * also removes its key), so nothing of what the user wrote, not even an empty ciphertext, stays on the phone; the next
 * entry starts a new file, and a new key.
 *
 * An entry the drain is sending is [claim]ed until [release]: an edit is never folded into it, because the request on its
 * way would then carry the old body and the removal that follows it would take the newer edit with it.
 */
class Outbox(
    private val store: TextStore,
    private val onQuarantine: () -> Unit = {},
    private val maxPayloadChars: Int = MAX_PAYLOAD_CHARS,
    private val eraseWhenEmpty: Boolean = false,
    private val clock: () -> Long,
) {
    /**
     * Adds the completion unless this Task is already queued; returns the entry that is queued either way, or null when it
     * is not safely kept. With a [holdMillis] the entry is held that long before it may be sent (the widget's undo window).
     */
    fun enqueue(taskId: String, version: Int, idempotencyKey: String, holdMillis: Long = 0L): OutboxEntry? =
        add(OutboxKind.TASK_COMPLETION, taskId, version, idempotencyKey, purchased = false, payload = null, holdMillis = holdMillis)

    /**
     * Adds a purchase (bought or put back, [purchased]) unless this item already has one queued; returns the entry that
     * is queued either way, so the caller shows the state that will be sent, not the one it asked for. Null when it is not safely kept
     * (a full queue, a failed or uncertain write): the caller retries with the same key.
     */
    fun enqueuePurchase(itemId: String, version: Int, purchased: Boolean, idempotencyKey: String): OutboxEntry? =
        add(OutboxKind.SHOPPING_PURCHASE, itemId, version, idempotencyKey, purchased, payload = null)

    /**
     * Adds the items request [bodyJson] for [listId] under [idempotencyKey], unless an add with that key is already
     * queued (the page retrying a tap whose first call did not report back); returns the entry that is queued either way.
     * Null when it is not safely kept: a full queue, a body over [MAX_PAYLOAD_CHARS], or a failed or uncertain write.
     */
    fun enqueueShoppingAdd(listId: String, bodyJson: String, idempotencyKey: String): OutboxEntry? {
        if (bodyJson.length > maxPayloadChars) return null
        return add(OutboxKind.SHOPPING_ADD, listId, 0, idempotencyKey, purchased = false, payload = bodyJson)
    }

    /**
     * Adds a record write: a new Task ([OutboxKind.TASK_CREATE], [subjectId] is [NEW_SUBJECT]), or an edit of the row
     * [subjectId] written against [version], with the request body the page built ([bodyJson], sent as it is) and the key
     * the first attempt carried. The same key queued again is the same write. A second edit of a Task or Project that
     * already has one waiting is folded into it (the later value of a field wins) while the first has never been tried,
     * under a new key; otherwise, and for any other kind, it is refused (null), never dropped unseen. Null also when it is
     * not safely kept: a full queue, a body over the cap, or a failed or uncertain write: the caller retries with the same key.
     */
    fun enqueueRecordWrite(kind: OutboxKind, subjectId: String, version: Int, bodyJson: String, idempotencyKey: String): OutboxEntry? {
        require(kind.sendsPayload && kind != OutboxKind.SHOPPING_ADD)
        if (bodyJson.length > maxPayloadChars) return null
        return add(kind, subjectId, version, idempotencyKey, purchased = false, payload = bodyJson)
    }

    /**
     * Set when a write ended as an [UncertainCommitException]: its text may be on disk (and is read back as the queue) but
     * the directory fsync that makes it survive a power cut failed. Cleared by the next write that succeeds, which syncs
     * the directory again with everything in the queue. A caller is not told "queued" while it is set.
     */
    private var unconfirmed = false

    /** The keys of the entries being sent now; in memory only, a restart sends nothing. */
    private val sending = HashSet<String>()

    /**
     * Takes [entry] to send it. False when it is no longer in the queue as it was read (an edit was folded into it, or it
     * was taken back): the drain skips it, and the entry that is there now is sent by the next run.
     */
    @Synchronized
    fun claim(entry: OutboxEntry): Boolean {
        val now = read()?.entries?.firstOrNull { it.idempotencyKey == entry.idempotencyKey } ?: return false
        if (now.failure != null || now.payload != entry.payload || now.version != entry.version) return false
        return sending.add(entry.idempotencyKey)
    }

    /** Ends the send that [claim] began, whatever came of it. */
    @Synchronized
    fun release(entry: OutboxEntry) {
        sending.remove(entry.idempotencyKey)
    }

    @Synchronized
    private fun add(
        kind: OutboxKind,
        subjectId: String,
        version: Int,
        idempotencyKey: String,
        purchased: Boolean,
        payload: String?,
        holdMillis: Long = 0L,
    ): OutboxEntry? {
        val current = read() ?: return null
        // A row has one pending write per kind; a write with no row yet is told by its key.
        val same: (OutboxEntry) -> Boolean =
            if (kind.keyed) {
                { it -> it.kind == kind && it.idempotencyKey == idempotencyKey }
            } else {
                { it -> it.kind == kind && it.subjectId == subjectId && it.failure == null }
            }
        current.entries.firstOrNull(same)?.let { existing ->
            if (kind.sendsPayload && existing.idempotencyKey != idempotencyKey) {
                // A different edit of a row that already has one waiting: folded in, or refused; never dropped.
                val folded = if (kind.mergesEdits && existing.attempts == 0 &&
                    existing.idempotencyKey !in sending
                ) {
                    fold(existing, version, payload)
                } else {
                    null
                }
                if (folded == null || folded.payload.orEmpty().length > maxPayloadChars) return null
                return if (write(current.copy(entries = current.entries.map { if (it === existing) folded else it }))) folded else null
            }
            // Readable is not durable: after an uncertain commit the entry is on disk, but a power cut may still lose it.
            // It is only reported as queued once the same queue has been written and synced successfully.
            return if (!unconfirmed || write(current)) existing else null
        }
        if (current.entries.size >= MAX_ENTRIES) return null
        val now = clock()
        val notBefore = if (holdMillis > 0) now + holdMillis.coerceAtMost(MAX_HOLD_MILLIS) else 0L
        val entry = OutboxEntry(
            subjectId,
            version,
            idempotencyKey,
            now,
            kind = kind,
            purchased = purchased,
            payload = payload,
            notBeforeMillis = notBefore,
        )
        return if (write(current.copy(entries = current.entries + entry))) entry else null
    }

    /**
     * [existing] with the fields of [newer] laid over it: the later value of a field wins, the version is the older of the
     * two (both rest on what the page last read). A new key, so a request of the old one that did get through is not
     * mistaken for this edit; the entry keeps its place in the queue. Null when a body is not a JSON object.
     */
    private fun fold(existing: OutboxEntry, version: Int, newer: String?): OutboxEntry? = try {
        val body = JSONObject(existing.payload ?: return null)
        val later = JSONObject(newer ?: return null)
        val kept = minOf(existing.version, version)
        for (name in later.keys()) body.put(name, later.get(name))
        body.put("version", kept)
        OutboxEntry(
            existing.subjectId,
            kept,
            idempotencyKey = foldedKey(existing.idempotencyKey),
            createdAtMillis = existing.createdAtMillis,
            kind = existing.kind,
            payload = body.toString(),
            issuedAtMillis = clock(),
        )
    } catch (_: JSONException) {
        null
    }

    /** The key of the later edit is the one the page made for it; [fold] needs one of its own that cannot clash with either. */
    private fun foldedKey(first: String): String = "$first.${clock()}".takeLast(MAX_KEY_LENGTH)

    /**
     * The entries to send, oldest first. An entry that has expired leaves them: a task completion is dropped (and
     * counted), a shopping write is kept as [failed] with [OutboxFailure.EXPIRED].
     */
    @Synchronized
    fun pending(): List<OutboxEntry> {
        val all = read() ?: return emptyList()
        val aged: (OutboxEntry) -> Boolean = {
            it.failure == null && (clock() - it.createdAtMillis > MAX_AGE_MILLIS || !it.keyStillSafe(clock()))
        }
        if (all.entries.none(aged)) return all.entries.filter { it.failure == null }
        val droppedTasks = all.entries.count { aged(it) && it.kind == OutboxKind.TASK_COMPLETION }
        val rest = all.entries.filterNot { aged(it) && it.kind == OutboxKind.TASK_COMPLETION }
            .map { if (aged(it)) it.copy(failure = OutboxFailure.EXPIRED) else it }
        write(Queue(rest, all.expired + droppedTasks))
        return rest.filter { it.failure == null }
    }

    /** The shopping writes that will not be sent unless the user retries them, oldest first. */
    @Synchronized
    fun failed(): List<OutboxEntry> {
        pending() // moves the entries that have just expired
        return read()?.entries?.filter { it.failure != null } ?: emptyList()
    }

    /** Keeps a shopping write the server refused for good, so the user can see it; a task completion is not kept (the widget's notice tells it). */
    @Synchronized
    fun markRejected(subjectId: String, idempotencyKey: String) {
        val all = read() ?: return
        write(
            all.copy(
                entries = all.entries.map {
                    if (it.matches(subjectId, idempotencyKey) &&
                        it.kind != OutboxKind.TASK_COMPLETION
                    ) {
                        it.copy(failure = OutboxFailure.REJECTED)
                    } else {
                        it
                    }
                },
            ),
        )
    }

    /**
     * Puts a failed write back to be sent again with its key, as new (the age counts from now). False when no such failed
     * entry exists, when its key is older than the server's idempotency window (it would be applied as a new write, so
     * it can only be removed), or when it could not be saved.
     */
    @Synchronized
    fun retryFailed(idempotencyKey: String): Boolean {
        val all = read() ?: return false
        val failed = all.entries.firstOrNull { it.idempotencyKey == idempotencyKey && it.failure != null } ?: return false
        if (!failed.keyStillSafe(clock())) return false
        return write(
            all.copy(
                entries = all.entries.map {
                    if (it.idempotencyKey == idempotencyKey &&
                        it.failure != null
                    ) {
                        it.copy(createdAtMillis = clock(), attempts = 0, failure = null)
                    } else {
                        it
                    }
                },
            ),
        )
    }

    /**
     * Takes a held task completion back before it is sent: the entry leaves the queue and nothing was ever requested.
     * False when no such entry is queued, or when its hold has ended (it may already be on its way, and Undo is then not
     * offered). Checked under the same lock as the drain's choice of what to send, so the two never both win.
     */
    @Synchronized
    fun undoHeld(taskId: String): Boolean {
        val all = read() ?: return false
        val now = clock()
        val rest = all.entries.filterNot {
            it.kind == OutboxKind.TASK_COMPLETION && it.subjectId == taskId && it.failure == null &&
                it.isHeld(now)
        }
        return rest.size != all.entries.size && write(all.copy(entries = rest))
    }

    /** When the earliest hold ends, or null when no entry is held: the time to come back and send. */
    @Synchronized
    fun nextSendAtMillis(): Long? {
        val now = clock()
        return pending().filter { it.isHeld(now) }.minOfOrNull { it.notBeforeMillis }
    }

    /** Removes a failed write for good. False when no such failed entry exists or it could not be saved. */
    @Synchronized
    fun discardFailed(idempotencyKey: String): Boolean {
        val all = read() ?: return false
        val rest = all.entries.filterNot { it.idempotencyKey == idempotencyKey && it.failure != null }
        return rest.size != all.entries.size && write(all.copy(entries = rest))
    }

    private fun OutboxEntry.matches(subjectId: String, idempotencyKey: String) =
        this.subjectId == subjectId && this.idempotencyKey == idempotencyKey

    /** How many queued completions expired unsent since the last [clearExpired]. Expired entries are dropped by [pending]. */
    @Synchronized
    fun expiredCount(): Int {
        pending()
        return read()?.expired ?: 0
    }

    /** Forgets the expired count once the user has been told. */
    @Synchronized
    fun clearExpired() {
        val all = read() ?: return
        if (all.expired > 0) write(all.copy(expired = 0))
    }

    /** Whether a completion of this Task is queued. */
    @Synchronized
    fun contains(taskId: String): Boolean = pending().any { it.kind == OutboxKind.TASK_COMPLETION && it.subjectId == taskId }

    /** Removes the entry once the server has answered finally (done, conflict, gone). Keys are unique to one entry. */
    @Synchronized
    fun remove(subjectId: String, idempotencyKey: String) {
        val all = read() ?: return
        val rest = all.entries.filterNot { it.subjectId == subjectId && it.idempotencyKey == idempotencyKey }
        if (rest.size != all.entries.size) write(all.copy(entries = rest))
    }

    /** Counts a failed attempt that will be retried with the same key. */
    @Synchronized
    fun recordAttempt(subjectId: String, idempotencyKey: String) {
        val all = read() ?: return
        write(
            all.copy(
                entries = all.entries.map {
                    if (it.subjectId == subjectId && it.idempotencyKey == idempotencyKey) it.withAttempt() else it
                },
            ),
        )
    }

    @Synchronized
    fun hasData(): Boolean = try {
        store.read() != null
    } catch (_: IOException) {
        true // something is there that cannot be read now; a caller cleaning up leftovers must still see it
    }

    @Synchronized
    fun clear() = store.delete()

    /** [clear] that proves the queue is gone: throws [java.io.IOException] when anything of it remains. */
    @Synchronized
    fun erase() = store.erase()

    /**
     * The stored queue; an empty one when there is no file. Null when the file could not be read: every change then
     * stops, so a passing read error never replaces the queued completions with a new, shorter queue.
     */
    private fun read(): Queue? {
        val text = try {
            store.read() ?: return Queue(emptyList(), 0)
        } catch (_: IOException) {
            return null
        }
        return try {
            val json = JSONObject(text)
            if (json.getInt("format") != FORMAT) return quarantined()
            val array = json.getJSONArray("entries")
            val entries = List(array.length()) {
                val row = array.getJSONObject(it)
                val kind = OutboxKind.ofWire(if (row.has("kind")) row.getString("kind") else null)
                    ?: return quarantined() // written by a newer app version: not ours to guess at
                OutboxEntry(
                    subjectId = row.getString("task"),
                    version = row.getInt("version"),
                    idempotencyKey = row.getString("key"),
                    createdAtMillis = row.getLong("at"),
                    attempts = row.optInt("attempts", 0),
                    kind = kind,
                    purchased = row.optBoolean("purchased", false),
                    payload = if (row.has("payload")) row.getString("payload") else null,
                    failure = if (row.has("failure")) OutboxFailure.ofWire(row.getString("failure")) else null,
                    issuedAtMillis = row.optLong("issued", row.getLong("at")),
                    notBeforeMillis = row.optLong("notBefore", 0L),
                )
            }
            Queue(entries, json.optInt("expired", 0).coerceAtLeast(0))
        } catch (_: JSONException) {
            quarantined()
        }
    }

    /**
     * The stored text cannot be parsed. It is moved aside as `<name>.corrupt` so the next write does not destroy it, and
     * the queue starts empty. If it cannot be moved, nothing is changed (null, like a read error).
     */
    private fun quarantined(): Queue? = try {
        store.quarantine()
        onQuarantine()
        Queue(emptyList(), 0)
    } catch (_: IOException) {
        null
    }

    private fun write(queue: Queue): Boolean {
        if (eraseWhenEmpty && queue.entries.isEmpty() && queue.expired == 0) return eraseStore()
        val array = JSONArray()
        for (entry in queue.entries) {
            // "task" is the row's id for every kind (the name predates purchases); a task entry is written exactly as
            // before, so an older app version still reads a queue that holds only completions.
            val row = JSONObject()
                .put("task", entry.subjectId)
                .put("version", entry.version)
                .put("key", entry.idempotencyKey)
                .put("at", entry.createdAtMillis)
                .put("attempts", entry.attempts)
                .put("issued", entry.issuedAtMillis)
            if (entry.notBeforeMillis > 0) row.put("notBefore", entry.notBeforeMillis)
            if (entry.kind != OutboxKind.TASK_COMPLETION) row.put("kind", entry.kind.wire).put("purchased", entry.purchased)
            entry.payload?.let { row.put("payload", it) }
            entry.failure?.let { row.put("failure", it.wire) }
            array.put(row)
        }
        val text = JSONObject().put("format", FORMAT).put("entries", array).put("expired", queue.expired).toString()
        return try {
            store.write(text)
            unconfirmed = false
            true
        } catch (_: UncertainCommitException) {
            // The write failed and its undo too: the file holds the old or the new queue. Only the file knows which, and
            // later changes read it (a queue that kept answering from the old one would lose the entry that is on disk, or
            // send one twice). But a readable file proves nothing about durability, so this is still a failed write: the
            // caller is told it is not saved, and retries with the same key, which finds the entry and syncs it again.
            // Unconditional: even when the file cannot be read back now, a later read may find the entry, and it must not
            // be reported as queued until a write has been synced.
            unconfirmed = true
            false
        } catch (_: IOException) {
            false
        }
    }

    /** An empty queue leaves no file and no key (see [eraseWhenEmpty]); false when something of it could not be removed. */
    private fun eraseStore(): Boolean = try {
        store.erase()
        unconfirmed = false
        true
    } catch (_: IOException) {
        false
    }

    /** What the file holds: the entries and the number that expired unsent (a plain count, no task data). */
    private data class Queue(val entries: List<OutboxEntry>, val expired: Int)

    companion object {
        private const val FORMAT = 1
        const val MAX_ENTRIES = 50

        /** The longest request body an add keeps (a batch of names is far below it): the queue file is rewritten on every change. */
        const val MAX_PAYLOAD_CHARS = 16 * 1024

        /** The longest body the journal queue keeps: the journal routes take up to 256 KB (`RequestPolicy.MAX_BODY_BYTES`). */
        const val MAX_JOURNAL_PAYLOAD_CHARS = 128 * 1024

        /** The subject of a write that has no row yet (a new Task, a new journal entry): the key tells such writes apart. */
        const val NEW_SUBJECT = "new"

        /** The longest idempotency key the server and the phone's request policy take. */
        private const val MAX_KEY_LENGTH = 128

        /** The longest a completion may be held for an Undo: a bound, so a held entry is always sent soon. */
        const val MAX_HOLD_MILLIS = 60_000L
        const val MAX_AGE_MILLIS = 7L * 24 * 60 * 60 * 1000

        /**
         * How long the server keeps a replay record: `IDEMPOTENCY_RETENTION` (30 days) in
         * backend/src/sidekick/shared/persistence/stores/base.py. After it a request with the same key is a new request.
         * Keep the two in step.
         */
        const val SERVER_IDEMPOTENCY_WINDOW_MILLIS = 30L * 24 * 60 * 60 * 1000

        /**
         * The oldest a key may be for the phone to send it: the server's window less a day, for the clock difference
         * and a request that is still on its way when the record is pruned. Counts from when the key was made, never
         * from a retry. An entry past it is never sent: it is kept as failed for the user to remove.
         */
        const val MAX_KEY_AGE_MILLIS = SERVER_IDEMPOTENCY_WINDOW_MILLIS - 24L * 60 * 60 * 1000
    }
}
