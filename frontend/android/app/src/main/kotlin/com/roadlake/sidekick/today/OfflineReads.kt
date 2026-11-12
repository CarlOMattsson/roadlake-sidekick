package com.roadlake.sidekick.today

import com.roadlake.sidekick.companion.CompanionClient
import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.PairingGeneration
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.io.IOException

/** A server answer, and when it is the offline copy: the epoch millis it was read from the server. */
class OfflineAnswer(val response: CompanionResponse, val cachedAtMillis: Long? = null)

/**
 * The offline copy of what the app opens without coverage: the last answer of each read the shopping room makes (the
 * page of lists and a list), the Agenda page of Arbete, and a Task's detail. A read that gets no answer at all
 * (`network`, `timeout`) is answered from the copy, marked with when it was read; every other outcome is the server's own.
 *
 * Reading is not the only thing that keeps the copy true. A write that the server accepted (a purchase or an edit of an
 * item, completing or reopening a Task) is applied to the copied answers it changes, so that going offline right after
 * ticking Milk does not bring Milk back as not bought (and a ticked Task back on the Agenda). It is applied only as far
 * as the answer can be known without asking: an item or a Task detail is merged with the server's new record, a completed
 * Task leaves the copied Agenda pages, and any change the copy cannot place (a reopened or rescheduled Task, which would
 * have to be sorted into the page) drops the Agenda copies instead. Dropping is honest: "could not be fetched" is better
 * than an Agenda that is wrong. The copy keeps its read time; a patch does not make it newer.
 *
 * Like [TodayCache] it belongs to one pairing: it is partitioned by the server host, written (by a read or a patch) only
 * while the pairing it began under is current ([PairingGeneration]), and erased when the pairing ends. It is bounded:
 * each [Slot] keeps its own number of reads (so that a busy Agenda does not push out a shopping list) of at most
 * [MAX_BODY_CHARS] each, the oldest replaced first. The Agenda is copied only for the plain page (no search text, which
 * is something the user typed, and no cursor, which is a later page). It holds what the lists and Tasks hold (names,
 * titles), nothing more, and is never logged.
 */
class OfflineReads(
    private val client: CompanionClient,
    private val store: TextStore,
    private val clock: () -> Long,
    private val generation: PairingGeneration = PairingGeneration(),
) {
    /** [CompanionClient.request], with the copy kept and used for the reads it covers and patched by the writes it follows. */
    fun request(
        method: String?,
        path: String?,
        query: Map<String, List<String>>?,
        bodyJson: String?,
        idempotencyKey: String?,
    ): OfflineAnswer {
        val key = keyOf(method, path, query)
        val write = if (key == null) writeOf(method, path) else null
        if (key == null && write == null) return OfflineAnswer(client.request(method, path, query, bodyJson, idempotencyKey))
        val captured = generation.current()
        val partition = client.status().serverHost ?: return OfflineAnswer(client.request(method, path, query, bodyJson, idempotencyKey))
        val response = try {
            client.request(method, path, query, bodyJson, idempotencyKey)
        } catch (e: CompanionException) {
            if (key == null || e.code !in NO_ANSWER) throw e
            val copy = recall(partition, key) ?: throw e
            return OfflineAnswer(CompanionResponse(200, copy.body), copy.atMillis)
        }
        if (key != null && response.status == 200 && response.body.length <= MAX_BODY_CHARS) {
            generation.runIfCurrent(captured) { remember(partition, key, response.body) }
        } else if (write != null && response.status in 200..299) {
            generation.runIfCurrent(captured) { amend(partition, write, response.body) }
        }
        return OfflineAnswer(response)
    }

    @Synchronized
    fun hasData(): Boolean = try {
        store.read() != null
    } catch (_: IOException) {
        true
    }

    @Synchronized
    fun clear() = store.delete()

    /** [clear] that proves the copy is gone: throws [IOException] when anything of it remains. */
    @Synchronized
    fun erase() = store.erase()

    private class Entry(val key: String, val atMillis: Long, val body: String)

    /** The reads the copy keeps apart, each with the number of reads it may hold. */
    enum class Slot(val max: Int) {
        SHOPPING(MAX_SHOPPING),
        AGENDA(MAX_AGENDA),
        TASK(MAX_TASKS),
    }

    @Synchronized
    private fun recall(partition: String, key: String): Entry? = read(partition).firstOrNull { it.key == key }

    @Synchronized
    private fun remember(partition: String, key: String, body: String) {
        val slot = slotOf(key)
        val others = read(partition).filter { it.key != key }
        val sameSlot = others.filter { slotOf(it.key) == slot }.take(slot.max - 1).toSet()
        val entries = listOf(Entry(key, clock(), body)) + others.filter { slotOf(it.key) != slot || it in sameSlot }
        save(partition, entries)
    }

    /**
     * Applies an accepted write ([write], answered with [body]) to every copied answer it changes. An answer that cannot
     * be understood, or would grow past [MAX_BODY_CHARS], is dropped: a copy that is not known to be right is not kept.
     */
    @Synchronized
    private fun amend(partition: String, write: Write, body: String) {
        val answer = try {
            JSONObject(body)
        } catch (_: JSONException) {
            return // nothing to learn from it; the next read replaces the copy
        }
        val before = read(partition)
        val after = before.mapNotNull { entry ->
            val slot = slotOf(entry.key)
            if (slot !in write.slots) return@mapNotNull entry
            val patched = try {
                write.patch(slot, JSONObject(entry.body), answer)
            } catch (_: JSONException) {
                null
            }
            when {
                patched == null -> null
                patched.length > MAX_BODY_CHARS -> null
                else -> Entry(entry.key, entry.atMillis, patched)
            }
        }
        if (before.size != after.size || before.zip(after).any { (a, b) -> a.body != b.body }) save(partition, after)
    }

    private fun save(partition: String, entries: List<Entry>) {
        val array = JSONArray()
        for (entry in entries) array.put(JSONObject().put("key", entry.key).put("at", entry.atMillis).put("body", entry.body))
        try {
            store.write(JSONObject().put("format", FORMAT).put("partition", partition).put("entries", array).toString())
        } catch (_: IOException) {
            // The copy is a convenience: the previous one stays, and the next read tries again.
        }
    }

    /** The stored reads of [partition], newest first; none when the file is missing, unreadable or of another server. */
    private fun read(partition: String): List<Entry> {
        val text = try {
            store.read()
        } catch (_: IOException) {
            null
        } ?: return emptyList()
        return try {
            val json = JSONObject(text)
            if (json.getInt("format") != FORMAT || json.getString("partition") != partition) return emptyList()
            val array = json.getJSONArray("entries")
            List(array.length()) {
                val row = array.getJSONObject(it)
                Entry(row.getString("key"), row.getLong("at"), row.getString("body"))
            }
        } catch (_: JSONException) {
            emptyList() // the next successful read replaces it
        }
    }

    /** An accepted write and how it changes a copied answer; null from [patch] means the answer is dropped. */
    private class Write(val slots: Set<Slot>, val patch: (slot: Slot, copy: JSONObject, answer: JSONObject) -> String?)

    companion object {
        private const val FORMAT = 1
        const val MAX_SHOPPING = 8
        const val MAX_AGENDA = 6
        const val MAX_TASKS = 12
        const val MAX_BODY_CHARS = 512 * 1024

        /** The failures in which no answer came: only then is the copy used. */
        private val NO_ANSWER = setOf("network", "timeout")

        private const val UUID = "[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}"

        /** The page of lists and one list (`/companion/v1/shopping/lists/{uuid}`), the reads the shopping room makes. */
        private val SHOPPING_READ = Regex("/companion/v1/shopping/lists(/$UUID)?")
        private const val AGENDA_PATH = "/companion/v1/work/agenda"
        private val TASK_DETAIL = Regex("/companion/v1/tasks/($UUID)")
        private val ITEM_WRITE = Regex("/companion/v1/shopping/items/($UUID)/(?:purchased|update)")
        private val TASK_WRITE = Regex("/companion/v1/tasks/($UUID)/(complete|reopen)")

        /** The query names that make an Agenda read something other than the plain page: typed text and a later page. */
        private val NOT_THE_PLAIN_AGENDA = setOf("q", "cursor")

        fun slotOf(key: String): Slot = when {
            key.startsWith(AGENDA_PATH) -> Slot.AGENDA
            key.startsWith("/companion/v1/tasks/") -> Slot.TASK
            else -> Slot.SHOPPING
        }

        /**
         * The key of a read the copy keeps, or null for any other request. `on_date` is left out: it only marks which
         * offers are current, and yesterday's copy of a list is still the list. The Agenda has no date argument, so all
         * of its filters count, except that a search (`q`) or a later page (`cursor`) is not kept.
         */
        fun keyOf(method: String?, path: String?, query: Map<String, List<String>>?): String? {
            if (method != "GET" || path == null) return null
            val given = query.orEmpty()
            val kept = when {
                SHOPPING_READ.matches(path) -> given.filterKeys { it != "on_date" }

                path == AGENDA_PATH -> given.takeIf { q ->
                    q.none { (name, values) -> name in NOT_THE_PLAIN_AGENDA && values.isNotEmpty() }
                }

                TASK_DETAIL.matches(path) -> given

                else -> null
            } ?: return null
            val parts = kept.toSortedMap().flatMap { (name, values) -> values.map { "$name=$it" } }
            return if (parts.isEmpty()) path else path + "?" + parts.joinToString("&")
        }

        /** The write that changes the copy, or null: purchasing or editing an item, completing or reopening a Task. */
        private fun writeOf(method: String?, path: String?): Write? {
            if (method != "POST" || path == null) return null
            ITEM_WRITE.matchEntire(path)?.let { return itemWrite(it.groupValues[1]) }
            TASK_WRITE.matchEntire(path)?.let { return taskWrite(it.groupValues[1], it.groupValues[2] == "complete") }
            return null
        }

        /**
         * The new record of an item, merged into the copied lists that hold it (a copy filtered by shop holds the item
         * or not, and the rest is left as it is), and the list's open count on the page of lists. The rows keep their
         * order: the server orders by when an item was made, which a purchase does not change.
         */
        private fun itemWrite(itemId: String) = Write(setOf(Slot.SHOPPING)) { _, copy, answer ->
            val item = answer.optJSONObject("item")
            if (item == null || !item.optString("id").equals(itemId, ignoreCase = true)) return@Write null
            val rows = copy.optJSONArray("items")
            if (rows != null) mergeInto(rows, itemId, item)
            val openCount = answer.opt("open_count")
            val lists = copy.optJSONArray("lists")
            if (lists != null && openCount is Int) {
                for (i in 0 until lists.length()) {
                    val row = lists.optJSONObject(i) ?: continue
                    if (row.optString("id") == item.optString("list_id")) row.put("open_count", openCount)
                }
            }
            copy.toString()
        }

        /**
         * A Task's tick. The detail copy takes the new version and status; the Agenda copies lose the Task when it is
         * now completed. Anything else (reopened, or completed but rolled forward by its recurrence) is a change the
         * Agenda page cannot be sorted for, so those copies are dropped. The answer is the whole Task or only a receipt
         * (`id`, `version`, `status`) for a device that may not read; either has what is needed.
         */
        private fun taskWrite(taskId: String, completing: Boolean) = Write(setOf(Slot.TASK, Slot.AGENDA)) { slot, copy, answer ->
            val record = answer.optJSONObject("task") ?: answer
            if (!record.optString("id").equals(taskId, ignoreCase = true)) return@Write null
            if (slot == Slot.AGENDA) {
                if (!completing || record.optString("status") != "completed") return@Write null
                copy.put("items", without(copy.getJSONArray("items"), taskId))
            } else {
                val task = copy.optJSONObject("task") ?: return@Write copy.toString()
                if (!task.optString("id").equals(taskId, ignoreCase = true)) return@Write copy.toString()
                for (name in record.keys()) if (name != "ok") task.put(name, record.get(name))
            }
            copy.toString()
        }

        private fun mergeInto(rows: JSONArray, id: String, record: JSONObject) {
            for (i in 0 until rows.length()) {
                val row = rows.optJSONObject(i) ?: continue
                if (!row.optString("id").equals(id, ignoreCase = true)) continue
                for (name in record.keys()) row.put(name, record.get(name))
            }
        }

        /** [rows] without the Task [taskId] itself (its Steps, which carry the same `task_id`, are other records). */
        private fun without(rows: JSONArray, taskId: String): JSONArray {
            val kept = JSONArray()
            for (i in 0 until rows.length()) {
                val row = rows.opt(i)
                val isTheTask =
                    row is JSONObject && row.optString("kind") == "task" && row.optString("id").equals(taskId, ignoreCase = true)
                if (!isTheTask) kept.put(row)
            }
            return kept
        }
    }
}
