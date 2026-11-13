package com.roadlake.sidekick.push

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import com.roadlake.sidekick.R
import com.roadlake.sidekick.widget.DeepLinks
import com.roadlake.sidekick.widget.WidgetLocale
import com.roadlake.sidekick.widget.WidgetLocaleStore
import org.json.JSONArray
import org.json.JSONException
import java.io.IOException

/** The texts of a notification from the string resources, in the app's own language (sv by default), not the system's. */
internal class AndroidReminderTexts(context: Context) : ReminderTexts {
    private val localized = WidgetLocale.localized(context, WidgetLocaleStore(context).get())

    override fun summary(today: Int, overdue: Int): String = ReminderSummaryText.compose(
        today = today,
        overdue = overdue,
        todayText = { localized.resources.getQuantityString(R.plurals.reminder_today, it, it) },
        overdueText = { localized.resources.getQuantityString(R.plurals.reminder_overdue, it, it) },
        join = { first, second -> localized.getString(R.string.reminder_summary_join, first, second) },
    )

    override fun dueAt(clock: String): String = localized.getString(R.string.reminder_due_at, clock)

    override fun test(): String = localized.getString(R.string.reminder_test)

    override fun publicTitle(count: Int): String = localized.resources.getQuantityString(R.plurals.reminder_public_title, count, count)
}

/**
 * Draws the reminders on the "Aviseringar" channel. Every notification is VISIBILITY_PRIVATE with a public version that
 * says only "Sidekick · N aviseringar" (D-079). The notification id comes from the reminder id, so showing a
 * reminder twice replaces it. The group notification is posted or updated when two or more of the app's reminder
 * notifications are on screen in total (counted with [ReminderGrouping]), not only when one batch holds several, so
 * reminders that arrive one by one in separate pushes still end up under "Sidekick · N aviseringar".
 */
internal class AndroidReminderDisplay(private val context: Context) : ReminderDisplay {
    // POST_NOTIFICATIONS is checked first by permitted(); lint cannot see through the helper.
    @SuppressLint("MissingPermission")
    override fun show(notices: List<ReminderNotice>) {
        if (notices.isEmpty() || !permitted()) return
        PushChannels.create(context)
        val manager = NotificationManagerCompat.from(context)
        for (notice in notices) {
            manager.notify(notice.notificationId, build(notice))
        }
        // The ids just posted are added to the active ones: the system registers a new notification asynchronously.
        val total = ReminderGrouping.summaryCount(activeIds() + notices.map { it.notificationId }, ReminderNotice.GROUP_ID)
        if (total >= ReminderGrouping.MIN_GROUPED) {
            manager.notify(ReminderNotice.GROUP_ID, buildGroup(AndroidReminderTexts(context).publicTitle(total)))
        }
    }

    override fun cancelAll() {
        val manager = NotificationManagerCompat.from(context)
        activeIds().forEach { manager.cancel(it) }
    }

    /** The ids of the reminder notifications that are on screen now (group summary included; the count leaves it out). */
    private fun activeIds(): List<Int> = (context.getSystemService(Context.NOTIFICATION_SERVICE) as? NotificationManager)
        ?.activeNotifications
        ?.filter { it.notification.group == GROUP }
        ?.map { it.id }
        .orEmpty()

    private fun permitted(): Boolean = Build.VERSION.SDK_INT < Build.VERSION_CODES.TIRAMISU ||
        ContextCompat.checkSelfPermission(context, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    private fun build(notice: ReminderNotice): Notification = base(notice.publicTitle)
        .setContentTitle(notice.title)
        .setContentText(notice.text)
        .setContentIntent(open(notice.notificationId, DeepLinks.view(context, notice.deepLink)))
        .setGroup(GROUP)
        .build()

    private fun buildGroup(publicTitle: String): Notification = base(publicTitle)
        .setContentTitle(publicTitle)
        .setContentIntent(open(ReminderNotice.GROUP_ID, DeepLinks.today(context)))
        .setGroup(GROUP)
        .setGroupSummary(true)
        .build()

    private fun base(publicTitle: String): NotificationCompat.Builder {
        val public = NotificationCompat.Builder(context, PushChannels.REMINDERS)
            .setSmallIcon(R.drawable.ic_notification)
            .setContentTitle(publicTitle)
            .build()
        return NotificationCompat.Builder(context, PushChannels.REMINDERS)
            .setSmallIcon(R.drawable.ic_notification)
            .setCategory(NotificationCompat.CATEGORY_REMINDER)
            .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
            .setPublicVersion(public)
            .setAutoCancel(true)
            // A repeated show (after a failed acknowledgement) replaces the notification without sounding again.
            .setOnlyAlertOnce(true)
    }

    // Explicit intent to the app's own activity, immutable; the request code keeps one PendingIntent per notification.
    private fun open(requestCode: Int, intent: android.content.Intent): PendingIntent =
        PendingIntent.getActivity(context, requestCode, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)

    private companion object {
        const val GROUP = "sidekick_reminders"
    }
}

/** [UnackedStore] in private preferences (a JSON array, oldest first). Reminder ids, never titles. */
internal class PreferencesUnackedStore(context: Context) : UnackedStore {
    private val preferences = context.applicationContext.getSharedPreferences("sidekick_reminders", Context.MODE_PRIVATE)

    override fun load(): List<String> {
        val text = preferences.getString(KEY, null) ?: return emptyList()
        return try {
            val array = JSONArray(text)
            (0 until array.length()).mapNotNull { array.optString(it).takeIf { id -> id.isNotEmpty() } }
        } catch (_: JSONException) {
            emptyList()
        }
    }

    override fun save(ids: List<String>) {
        preferences.edit().apply { if (ids.isEmpty()) remove(KEY) else putString(KEY, JSONArray(ids).toString()) }.apply()
    }

    // commit(): emptying the list at the end of a pairing must be on disk, and say so when it is not.
    @SuppressLint("ApplySharedPref")
    override fun clear() {
        if (!preferences.edit().remove(KEY).commit() || preferences.contains(KEY)) throw IOException("reminder ids remain")
    }

    private companion object {
        const val KEY = "shown_unacked"
    }
}
