package com.roadlake.sidekick.push

import com.roadlake.sidekick.companion.CompanionException
import com.roadlake.sidekick.companion.CompanionResponse
import com.roadlake.sidekick.companion.OwnerZone
import com.roadlake.sidekick.companion.PairingGeneration
import com.roadlake.sidekick.widget.DeepLinks
import org.json.JSONArray
import org.json.JSONException
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.GregorianCalendar
import java.util.Locale
import java.util.TimeZone

/** The two server routes of the visible reminders (`/companion/v1/reminders/...`, D-078). */
interface RemindersApi {
    fun pending(): CompanionResponse

    fun ack(ids: List<String>): CompanionResponse
}

enum class ReminderKind { DUE, TEST }

/** One reminder to show. [dueAtMillis] is null when the server sent no time. */
class ReminderItem(val id: String, val kind: ReminderKind, val title: String, val taskId: String?, val dueAtMillis: Long?)

/** The morning summary: how many Tasks are due today and how many are overdue. */
class ReminderSummary(val id: String, val today: Int, val overdue: Int)

/** What `GET /companion/v1/reminders/pending` says. Items of a kind this app does not know are left out (never acked). */
class PendingReminders(
    val items: List<ReminderItem>,
    val summary: ReminderSummary?,
    /** The owner's zone from the answer's `timezone`; null when it was missing or unknown (the device's zone is used). */
    val zone: TimeZone? = null,
) {
    /** Everything that is shown (or would be, without permission) and is acknowledged afterwards, the summary included. */
    val ids: List<String> get() = listOfNotNull(summary?.id) + items.map { it.id }
}

object RemindersCodec {
    private const val MAX_ID_CHARS = 64
    private const val MAX_TITLE_CHARS = 200
    private val UUID = Regex("[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}")

    /** The reminders of a response body, or null when the body is not the expected JSON (nothing is shown, nothing is acked). */
    fun parse(body: String): PendingReminders? = try {
        val json = JSONObject(body)
        val seen = HashSet<String>()
        val items = ArrayList<ReminderItem>()
        val array = json.optJSONArray("items") ?: JSONArray()
        for (index in 0 until array.length()) {
            val entry = array.optJSONObject(index) ?: continue
            val item = item(entry) ?: continue
            if (seen.add(item.id)) items += item
        }
        val summary = summary(json.optJSONObject("summary"))?.takeIf { it.id !in seen }
        PendingReminders(items, summary, zone(json.opt("timezone")))
    } catch (_: JSONException) {
        null
    }

    private fun zone(value: Any?): TimeZone? = OwnerZone.idOf(value)?.let(TimeZone::getTimeZone)

    private fun id(entry: JSONObject): String? = (entry.opt("id") as? String)?.takeIf { it.isNotEmpty() && it.length <= MAX_ID_CHARS }

    private fun item(entry: JSONObject): ReminderItem? {
        val id = id(entry) ?: return null
        val kind = when (entry.opt("kind")) {
            "due" -> ReminderKind.DUE
            "test" -> ReminderKind.TEST
            else -> return null
        }
        val title = (entry.opt("title") as? String)?.trim().orEmpty().take(MAX_TITLE_CHARS)
        if (kind == ReminderKind.DUE && title.isEmpty()) return null
        // The id goes into a deep link, so only a real Task id is used; anything else opens Today instead.
        val taskId = (entry.opt("task_id") as? String)?.takeIf { UUID.matches(it) }
        val dueAt = (entry.opt("due_at") as? String)?.let(IsoInstant::parse)
        return ReminderItem(id, kind, title, taskId, dueAt)
    }

    private fun summary(entry: JSONObject?): ReminderSummary? {
        entry ?: return null
        val id = id(entry) ?: return null
        val today = (entry.opt("today") as? Int)?.takeIf { it >= 0 } ?: return null
        val overdue = (entry.opt("overdue") as? Int)?.takeIf { it >= 0 } ?: return null
        return ReminderSummary(id, today, overdue)
    }
}

/** An ISO 8601 instant ("2026-11-08T14:30:00Z", with fraction and offset allowed) as epoch millis. Plain java.util: minSdk 24. */
object IsoInstant {
    private val PATTERN =
        Regex("""(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(Z|[+-]\d{2}:?\d{2})""")

    fun parse(text: String): Long? {
        val match = PATTERN.matchEntire(text) ?: return null
        val (year, month, day, hour, minute, second, zone) = match.destructured
        val calendar = GregorianCalendar(TimeZone.getTimeZone("UTC"), Locale.ROOT)
        calendar.isLenient = false
        return try {
            calendar.clear()
            calendar.set(year.toInt(), month.toInt() - 1, day.toInt(), hour.toInt(), minute.toInt(), second.toInt())
            calendar.timeInMillis - offsetMillis(zone)
        } catch (_: IllegalArgumentException) {
            null
        }
    }

    private fun offsetMillis(zone: String): Long {
        if (zone == "Z") return 0
        val sign = if (zone[0] == '-') -1 else 1
        val digits = zone.substring(1).replace(":", "")
        return sign * (digits.substring(0, 2).toLong() * 60 + digits.substring(2, 4).toLong()) * 60_000
    }

    /** "HH:mm" of [millis] on the wall clock of [zone]. */
    fun clock(millis: Long, zone: TimeZone): String = SimpleDateFormat("HH:mm", Locale.ROOT).apply { timeZone = zone }.format(millis)
}

/** The words of a notification, in the app's language ([com.roadlake.sidekick.widget.WidgetLocale]), not the system's. */
interface ReminderTexts {
    fun summary(today: Int, overdue: Int): String

    fun dueAt(clock: String): String

    fun test(): String

    /** The lock-screen version: "Sidekick · N aviseringar". Never a title. */
    fun publicTitle(count: Int): String
}

sealed interface ReminderTarget {
    data object Today : ReminderTarget

    class Task(val id: String) : ReminderTarget
}

/** One notification, ready to draw. [id] is the server's reminder id: the same id is the same notification. */
class ReminderNotice(val id: String, val title: String, val text: String?, val target: ReminderTarget, val publicTitle: String) {
    /** The same notification id for the same reminder id, so a repeated show replaces instead of duplicating. */
    val notificationId: Int get() = notificationIdOf(id)

    /** The app's deep link (`launch-hint.ts`) that a tap opens. */
    val deepLink: String
        get() = when (target) {
            ReminderTarget.Today -> DeepLinks.TODAY_URI
            is ReminderTarget.Task -> DeepLinks.taskUri(target.id)
        }

    companion object {
        /** The id of the group summary; reminder ids map to 1000 and up. */
        const val GROUP_ID = 1

        fun notificationIdOf(reminderId: String): Int = 1000 + (reminderId.hashCode() and 0x3fffffff)
    }
}

/** The morning summary as one line: only the parts that are not zero ("3 uppgifter idag", "1 försenad uppgift", both joined). */
object ReminderSummaryText {
    /**
     * Zero overdue leaves the overdue part out and zero today the today part, so the line never says "0 försenade
     * uppgifter". With nothing in either the line is the (zero) today part, never empty; [ReminderNotices.plan] draws no
     * summary at all then. The parts come from plural resources.
     */
    fun compose(
        today: Int,
        overdue: Int,
        todayText: (Int) -> String,
        overdueText: (Int) -> String,
        join: (String, String) -> String,
    ): String = when {
        today > 0 && overdue > 0 -> join(todayText(today), overdueText(overdue))
        overdue > 0 -> overdueText(overdue)
        else -> todayText(today)
    }
}

object ReminderNotices {
    /**
     * The notifications of [pending]: the summary first, then one per reminder. A summary of nothing due and nothing
     * overdue says nothing worth a notification and is left out (it is still acknowledged with the rest).
     */
    fun plan(pending: PendingReminders, texts: ReminderTexts, zone: TimeZone): List<ReminderNotice> {
        val summary = pending.summary?.takeIf { it.today > 0 || it.overdue > 0 }
        val publicTitle = texts.publicTitle(pending.items.size + if (summary != null) 1 else 0)
        val notices = ArrayList<ReminderNotice>()
        summary?.let {
            notices += ReminderNotice(it.id, texts.summary(it.today, it.overdue), null, ReminderTarget.Today, publicTitle)
        }
        for (item in pending.items) {
            notices += when (item.kind) {
                ReminderKind.TEST -> ReminderNotice(item.id, texts.test(), null, ReminderTarget.Today, publicTitle)

                ReminderKind.DUE -> ReminderNotice(
                    id = item.id,
                    title = item.title,
                    text = item.dueAtMillis?.let { texts.dueAt(IsoInstant.clock(it, zone)) },
                    target = item.taskId?.let { ReminderTarget.Task(it) } ?: ReminderTarget.Today,
                    publicTitle = publicTitle,
                )
            }
        }
        return notices
    }
}

/** When reminder notifications are grouped, and under what count. Pure, so it is tested on the JVM. */
object ReminderGrouping {
    /** From this many reminder notifications on screen a group notification is shown; one alone needs none. */
    const val MIN_GROUPED = 2

    /** The number of distinct reminder notifications among [activeIds], the group summary ([groupId]) left out. */
    fun summaryCount(activeIds: Collection<Int>, groupId: Int): Int = activeIds.filter { it != groupId }.toSet().size
}

/** Draws the notifications; two or more on screen, also from separate pushes, are grouped under one. The Android side is [AndroidReminderDisplay]. */
fun interface ReminderDisplay {
    fun show(notices: List<ReminderNotice>)

    /** Takes down every reminder notification this app has on screen (the pairing they belong to has ended). */
    fun cancelAll() = Unit
}

/** The ids that were shown but whose acknowledgement did not get through. Android: private preferences; tests: memory. */
interface UnackedStore {
    fun load(): List<String>

    fun save(ids: List<String>)

    /** Forgets every id and proves it: throws [java.io.IOException] when some remain. */
    @Throws(java.io.IOException::class)
    fun clear() = save(emptyList())
}

/**
 * Fetch, show, acknowledge (D-078). Free of Android types and logging, so it is unit tested on the JVM.
 *
 * Without the notification permission nothing is shown, but the acknowledgement is still sent so the server does not
 * collect reminders. The shown ids are kept in [unacked] until the acknowledgement is accepted: a failed one is tried
 * again with the next fetch, together with the new ids, and the reminders that come back are not shown a second time.
 * The list holds at most [MAX_UNACKED] ids, the oldest dropped first. Times are in the owner's zone from the answer,
 * or, when the answer has none, in [deviceZone] (the owner's zone the pairing stored, the phone's own only when the
 * server never said one). Titles are never logged.
 *
 * A run belongs to the pairing it began under ([PairingGeneration]): its requests are pinned to it, and showing and
 * remembering are made only while that pairing is current. Reminders fetched for a pairing that has ended meanwhile are
 * not shown, not remembered and not acknowledged (the next pairing fetches its own). [clearLocal] ends what a pairing
 * leaves behind: the notifications on screen and the ids still waiting for an acknowledgement.
 */
class ReminderFlow(
    private val api: RemindersApi,
    private val permitted: () -> Boolean,
    private val display: ReminderDisplay,
    private val texts: () -> ReminderTexts,
    private val deviceZone: () -> TimeZone,
    private val unacked: UnackedStore,
    private val generation: PairingGeneration = PairingGeneration(),
) {
    fun run(): SyncOutcome {
        val captured = generation.current()
        return generation.pinned(captured) { runFor(captured) }
    }

    /** Every end of a pairing: the notifications and the unacknowledged ids belong to it, so they go. */
    @Throws(java.io.IOException::class)
    fun clearLocal() {
        unacked.clear()
        try {
            display.cancelAll()
        } catch (_: RuntimeException) {
            // Notifications that cannot be reached are the system's to drop; the ids are already forgotten.
        }
    }

    private fun runFor(captured: Long): SyncOutcome {
        val pending = try {
            api.pending()
        } catch (e: CompanionException) {
            return failed(e)
        }
        when {
            pending.status in 200..299 -> Unit

            // 401: the pairing is gone. Other 4xx: trying the same again changes nothing.
            pending.status in 400..499 -> return SyncOutcome.DONE

            else -> return SyncOutcome.RETRY
        }
        val reminders = RemindersCodec.parse(pending.body) ?: return SyncOutcome.DONE
        val earlier = unacked.load()
        val fresh = reminders.withoutIds(earlier.toSet())
        val ids = (earlier + reminders.ids).distinct()
        if (ids.isEmpty()) return SyncOutcome.DONE

        val remembered = generation.runIfCurrent(captured) {
            if (fresh.ids.isNotEmpty() && permitted()) {
                try {
                    display.show(ReminderNotices.plan(fresh, texts(), reminders.zone ?: deviceZone()))
                } catch (_: RuntimeException) {
                    // A notification that cannot be drawn (permission withdrawn meanwhile) is the same as "no permission".
                }
            }
            // Remembered before the call, so a lost answer or a crash still leaves the ids to be acknowledged next time.
            unacked.save(ids.takeLast(MAX_UNACKED))
        }
        if (!remembered) return SyncOutcome.DONE
        val ack = try {
            api.ack(ids)
        } catch (e: CompanionException) {
            return failed(e)
        }
        if (ack.status >= 500) return SyncOutcome.RETRY
        generation.runIfCurrent(captured) { unacked.save(emptyList()) }
        return SyncOutcome.DONE
    }

    private fun failed(e: CompanionException) = if (e.code == "not_paired") SyncOutcome.DONE else SyncOutcome.RETRY

    private fun PendingReminders.withoutIds(skip: Set<String>) =
        PendingReminders(items.filter { it.id !in skip }, summary?.takeIf { it.id !in skip }, zone)

    companion object {
        const val MAX_UNACKED = 50
    }
}
