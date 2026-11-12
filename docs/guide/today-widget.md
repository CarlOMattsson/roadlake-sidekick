# The Today widget and reminders

[Svenska](today-widget.sv.md)

<!-- description: The Today widget shows today's tasks on your Android home screen. Reminders arrive through ntfy and UnifiedPush, with no Google services. -->

The Today widget shows today's tasks on your Android home screen. Reminders tell you in the morning and shortly before something is due. Both belong to the [Android app](android-app.md).

:::note[Preview]
The widget and the reminders have not been tried on a real phone. Push delivery to real phones is not verified.
:::

## Add the widget

1. Pair the app with your server.
2. Press and hold an empty spot on the home screen and choose widgets.
3. Choose Sidekick's widget and drag it out.

The widget starts at 4 × 2 cells, and you can resize it. Before the app is paired, the widget shows a button that opens the app's pairing screen.

## Check off a task in the widget

You check a task off right in the widget. You do not need to open the app.

## How often the widget refreshes

The widget fetches today's tasks about every 30 minutes. A task you just created in Claude can therefore take a while to show up.

## The coin in the widget's header

Without a license key the widget shows a small coin in its header. That is the reminder that this is the free version. Tapping the coin opens the app. A valid key removes the coin and changes nothing else.

## What Sidekick reminds you about

- **The morning summary** arrives in the morning, but only if something is due today or overdue.
- **Due soon** arrives a little before a task with a clock time is due.

Nothing is announced during the quiet hours in the evening and at night. The times are set on the server.

## How reminders reach you

Reminders travel through UnifiedPush, an open way to wake an app, and the ntfy app on the phone. Sidekick does not use Firebase and does not depend on Google services.

What is sent is a wake-up with no content. The phone wakes, fetches what is due from your server and shows the notification itself. What appears on the lock screen follows the phone's own setting.

## Turn on reminders

1. Ask whoever runs the server to turn on reminders. [Read how to set up reminders through ntfy](../operate/push-reminders.md).
2. Install the ntfy app on the phone and open it once.
3. Allow notifications for Sidekick. Android 13 and newer ask once after pairing.
4. Open Settings in Sidekick and choose "Send test notification".

On recent Android versions, ntfy needs unrestricted battery use. Otherwise wake-ups can be delayed.

## If nothing arrives

Settings in the app says what is missing: the ntfy app, notification permission or reminders on the server. [Go to troubleshooting in the operations guide](../operate/pair-android.md).
