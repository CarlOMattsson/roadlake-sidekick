package com.roadlake.sidekick.push

import com.roadlake.sidekick.SidekickRuntime
import com.roadlake.sidekick.widget.TodaySync
import org.unifiedpush.android.connector.FailedReason
import org.unifiedpush.android.connector.PushService
import org.unifiedpush.android.connector.data.PushEndpoint
import org.unifiedpush.android.connector.data.PushMessage

/**
 * The receiver of the UnifiedPush distributor's events (ntfy). The WebView is never started from here.
 *
 * Nothing is logged: an endpoint is a capability to wake this phone, and a message is content-free by contract.
 */
class SidekickPushService : PushService() {
    private val receiver = PushReceiver(
        // Something changed elsewhere: read Today again in the background, as after the app comes to the foreground.
        onWake = { TodaySync.requestSync(applicationContext) },
        // There are reminders to show: fetch them, show them, acknowledge them (a worker with a network and retry).
        onReminders = { ReminderSync.schedule(applicationContext) },
    )

    override fun onMessage(message: PushMessage, instance: String) = receiver.handle(message.content)

    override fun onNewEndpoint(endpoint: PushEndpoint, instance: String) {
        if (SidekickRuntime.get(this).push.onNewEndpoint(endpoint.url)) PushSync.schedule(applicationContext)
    }

    override fun onUnregistered(instance: String) {
        if (SidekickRuntime.get(this).push.onUnregistered()) PushSync.schedule(applicationContext)
    }

    /** The distributor could not register the app (no network, action required). The next start tries again; it is not an error to show. */
    override fun onRegistrationFailed(reason: FailedReason, instance: String) = Unit
}
