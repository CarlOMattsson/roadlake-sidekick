package com.roadlake.sidekick.today

import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject

/**
 * One row of Today as the widget and the app share it: what to show and what to send to complete it. Nothing else of
 * the Task is kept (no description, no notes, no due time, no project, no contact): the cache is a title list with the
 * versions the completion needs.
 */
class TodayTask(val id: String, val title: String, val version: Int, val overdue: Boolean)

/**
 * Why the list changed under the user's finger; shown once, in the widget's footer, until the next clean read.
 * [EXPIRED]: a completion waited in the outbox for longer than it may and was dropped without being sent.
 */
enum class TodayNotice { CONFLICT, REJECTED, EXPIRED }

/**
 * The cached Today: at most [MAX_TASKS] rows, read at [syncedAtMillis] from the server whose origin is [partition].
 * [total] is the server's own count of Today's rows (overdue and due today), also those that were not read; the widget's
 * "+N till" is [total] minus the rows it shows. [day] is the server's calendar day of the read (installation time zone).
 * [offline] is true when the last attempt to read Today did not get through (no network, no answer): the widget then says
 * "Offline" with [syncedAtMillis], the time of the last read that did.
 */
class TodaySnapshot(
    val partition: String,
    val syncedAtMillis: Long,
    val tasks: List<TodayTask>,
    val total: Int,
    val notice: TodayNotice? = null,
    val day: String = "",
    val offline: Boolean = false,
) {
    fun without(taskId: String): TodaySnapshot {
        val kept = tasks.filter { it.id != taskId }
        val removed = tasks.size - kept.size
        return copy(tasks = kept, total = (total - removed).coerceAtLeast(kept.size))
    }

    fun withNotice(value: TodayNotice?) = copy(notice = value)

    fun withOffline(value: Boolean) = copy(offline = value)

    private fun copy(
        tasks: List<TodayTask> = this.tasks,
        total: Int = this.total,
        notice: TodayNotice? = this.notice,
        offline: Boolean = this.offline,
    ) = TodaySnapshot(partition, syncedAtMillis, tasks, total, notice, day, offline)

    companion object {
        /** The widget shows 5-7 rows; the rest is read for the "+N till" line, bounded to 20 rows. */
        const val MAX_TASKS = 20
        const val MAX_TITLE_CHARS = 120
    }
}

/** The JSON of a [TodaySnapshot] on disk, and the reading of the server's Today into one. */
object TodayCodec {
    private const val FORMAT = 2
    private val UUID = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

    fun encode(snapshot: TodaySnapshot): String {
        val tasks = JSONArray()
        for (task in snapshot.tasks.take(TodaySnapshot.MAX_TASKS)) {
            tasks.put(
                JSONObject()
                    .put("id", task.id)
                    .put("title", task.title)
                    .put("version", task.version)
                    .put("overdue", task.overdue),
            )
        }
        return JSONObject()
            .put("format", FORMAT)
            .put("partition", snapshot.partition)
            .put("syncedAt", snapshot.syncedAtMillis)
            .put("total", snapshot.total)
            .put("day", snapshot.day)
            .put("notice", snapshot.notice?.name ?: JSONObject.NULL)
            .put("offline", snapshot.offline)
            .put("tasks", tasks)
            .toString()
    }

    /** The snapshot a text holds, or null for anything that is not exactly this format (then it is not used). */
    fun decode(text: String?): TodaySnapshot? {
        if (text == null) return null
        return try {
            val json = JSONObject(text)
            if (json.getInt("format") != FORMAT) return null
            val tasks = json.getJSONArray("tasks")
            val rows = ArrayList<TodayTask>(tasks.length())
            for (i in 0 until minOf(tasks.length(), TodaySnapshot.MAX_TASKS)) {
                val row = tasks.getJSONObject(i)
                rows += TodayTask(
                    id = row.getString("id"),
                    title = row.getString("title"),
                    version = row.getInt("version"),
                    overdue = row.getBoolean("overdue"),
                )
            }
            TodaySnapshot(
                partition = json.getString("partition"),
                syncedAtMillis = json.getLong("syncedAt"),
                tasks = rows,
                total = json.getInt("total"),
                notice = json.optString("notice").let { name -> TodayNotice.entries.firstOrNull { it.name == name } },
                day = json.getString("day"),
                offline = json.optBoolean("offline", false),
            )
        } catch (_: JSONException) {
            null
        }
    }

    /**
     * Today out of `GET /companion/v1/work/today?limit=20`: the server has already chosen the open Tasks (overdue first,
     * then due today, in the installation's time zone) and counted them in `total`, so nothing is filtered here. Each
     * row is reduced to [TodayTask]; a row without a well-formed id, title or version is skipped. A body that is not a
     * Today page is a `bad_response`.
     */
    fun fromToday(body: String, partition: String, nowMillis: Long): TodaySnapshot {
        try {
            val json = JSONObject(body)
            val items = json.getJSONArray("items")
            val rows = ArrayList<TodayTask>()
            for (i in 0 until items.length()) {
                val item = items.getJSONObject(i)
                val id = item.optString("id")
                val title = item.optString("title").trim()
                if (!UUID.matches(id) || title.isEmpty() || !item.has("version")) continue
                rows += TodayTask(id.lowercase(), clip(title), item.getInt("version"), item.optString("group") == "overdue")
            }
            val shown = rows.take(TodaySnapshot.MAX_TASKS)
            val total = json.getInt("total").coerceAtLeast(shown.size)
            return TodaySnapshot(partition, nowMillis, shown, total, day = json.getString("day"))
        } catch (_: JSONException) {
            throw com.roadlake.sidekick.companion.CompanionException("bad_response")
        }
    }

    private fun clip(title: String): String = if (title.length <= TodaySnapshot.MAX_TITLE_CHARS) {
        title
    } else {
        title.substring(0, TodaySnapshot.MAX_TITLE_CHARS - 1).trimEnd() + "…"
    }
}
