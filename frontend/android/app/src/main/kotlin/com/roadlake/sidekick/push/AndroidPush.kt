package com.roadlake.sidekick.push

import android.Manifest
import android.app.Activity
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.content.Context
import android.os.Build
import androidx.core.app.ActivityCompat
import androidx.core.app.NotificationManagerCompat
import com.roadlake.sidekick.R
import com.roadlake.sidekick.widget.WidgetLocale
import com.roadlake.sidekick.widget.WidgetLocaleStore
import org.unifiedpush.android.connector.UnifiedPush
import java.lang.ref.WeakReference

/** The activity in the foreground, if any. The distributor picker and the permission question need one. */
class ForegroundActivity {
    @Volatile
    private var current: WeakReference<Activity>? = null

    fun get(): Activity? = current?.get()

    fun set(activity: Activity) {
        current = WeakReference(activity)
    }

    fun clear(activity: Activity) {
        if (current?.get() === activity) current = null
    }
}

/** UnifiedPush (the connector library), behind [PushDistributor]. */
class UnifiedPushDistributor(private val context: Context, private val foreground: ForegroundActivity) : PushDistributor {
    override fun available(): Boolean = UnifiedPush.getDistributors(context).isNotEmpty()

    /**
     * With an activity in the foreground the library may pick the distributor (the only one, the saved one, or ask the
     * user when several are installed) and then registers. Without one (background), only an already saved choice is used.
     */
    override fun register() {
        val activity = foreground.get()
        if (activity != null) {
            UnifiedPush.tryUseCurrentOrDefaultDistributor(activity) { success ->
                if (success) UnifiedPush.register(context)
            }
        } else if (UnifiedPush.getSavedDistributor(context) != null) {
            UnifiedPush.register(context)
        }
    }

    override fun unregister() {
        if (UnifiedPush.getSavedDistributor(context) != null) UnifiedPush.unregister(context)
    }
}

/** The rule behind the notification permission, apart from the Android calls so it is tested on the JVM. */
object NotificationPermissionRules {
    const val ASKABLE_FROM_SDK = 33

    /**
     * Granted when notifications are enabled. Otherwise denied when the user cannot be asked (below Android 13 the
     * switch is in the system settings) or already was; the question is asked once, so it is PROMPT only before that.
     */
    fun resolve(sdk: Int, enabled: Boolean, asked: Boolean): PermissionState = when {
        enabled -> PermissionState.GRANTED
        sdk < ASKABLE_FROM_SDK || asked -> PermissionState.DENIED
        else -> PermissionState.PROMPT
    }
}

/** POST_NOTIFICATIONS: the state from the system, and one question, remembered in private preferences. */
class AndroidNotificationGate(private val context: Context, private val foreground: ForegroundActivity) : NotificationGate {
    private val preferences = context.getSharedPreferences(PREFERENCES, Context.MODE_PRIVATE)

    override fun state(): PermissionState = NotificationPermissionRules.resolve(
        sdk = Build.VERSION.SDK_INT,
        enabled = NotificationManagerCompat.from(context).areNotificationsEnabled(),
        asked = preferences.getBoolean(ASKED, false),
    )

    override fun ask() {
        // Without an activity in the foreground nothing can be shown; the question stays unasked.
        val activity = foreground.get() ?: return
        preferences.edit().putBoolean(ASKED, true).apply()
        ActivityCompat.requestPermissions(activity, arrayOf(Manifest.permission.POST_NOTIFICATIONS), REQUEST_CODE)
    }

    private companion object {
        const val PREFERENCES = "sidekick_push"
        const val ASKED = "asked_post_notifications"
        const val REQUEST_CODE = 7421
    }
}

/**
 * The two notification channels (D-078): "Påminnelser" for the visible reminders, "Synk" for the quiet
 * sync, which shows no notification of its own. The lock screen shows no content on either (the notification builder,
 * a later step, uses the private visibility too). Creating a channel again changes nothing.
 */
object PushChannels {
    const val REMINDERS = "reminders"
    const val SYNC = "sync"

    fun create(context: Context) {
        if (Build.VERSION.SDK_INT < Build.VERSION_CODES.O) return
        val manager = context.getSystemService(NotificationManager::class.java) ?: return
        // The names follow the app's language (sv by default), not the system's. Creating a channel again renames it.
        val names = WidgetLocale.localized(context, WidgetLocaleStore(context).get())
        manager.createNotificationChannel(
            NotificationChannel(REMINDERS, names.getString(R.string.channel_reminders), NotificationManager.IMPORTANCE_DEFAULT)
                .apply { lockscreenVisibility = Notification.VISIBILITY_PRIVATE },
        )
        manager.createNotificationChannel(
            NotificationChannel(SYNC, names.getString(R.string.channel_sync), NotificationManager.IMPORTANCE_MIN)
                .apply {
                    lockscreenVisibility = Notification.VISIBILITY_SECRET
                    setShowBadge(false)
                },
        )
    }
}
