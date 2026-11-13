# The Android app

[Svenska](android-app.sv.md)

<!-- description: The Android app shows Work, Journal and Shopping from the same server as Claude. What the app does, what it does not do, and how to get started. -->

The Android app is a second surface for the same Sidekick server, next to Claude. It shows the same records from the same database. From the first release on, every release on GitHub Releases carries a signed APK, `sidekick-X.Y.Z.apk`, that you install directly. You can also build the app yourself from the source code.

:::note[First release]
The app is in daily use on a real phone against a real server. It is also built and tested automatically, including on an emulator.
:::

## What the app does

- **Work:** today's agenda, projects, tasks and steps. You can read them, check them off and reopen them.
- **Shopping:** lists and items. You can create lists, add, edit, tick off and undo.
- **Journal:** read days and entries, and write or edit entries by hand.
- **The Today widget:** today's tasks on your home screen. [Read about the widget and reminders](today-widget.md).
- **Settings:** notification status, a test notification, the app's language, the phone's connection, the option to disconnect the phone and the license key.

## What the app does not do

- It does not create tasks or projects. You do that in Claude.
- It runs no AI and does not talk to Claude.
- It does not show Contacts or Control.
- It does not change tags and has no tag filter, and it does not show the actions on a step.
- It has no QR scanner and does not ask for the camera.
- It does not back up its connection or transfer it to a new phone.

There is no iOS app.

## What you need

- A phone with Android 7.0 or newer and an up-to-date Android System WebView, version 123 or newer.
- A Sidekick server that the phone reaches over HTTPS at a public address.
- The signed APK from a release, or a computer where you build the app yourself.

The work-laptop package has no route to a phone.

## Get started

1. Download the APK from the release, or build it yourself, and install it on the phone.
2. Turn on the app's connection on the server.
3. Create a pairing code on the server. The code works once and for ten minutes.
4. Open the app, enter the server's address and the code, and tap Connect.

Every command is in the operations guide. [Read how to install and pair the Android app](../operate/pair-android.md). [Read how to check a release's files](../maintainers/release.md#verifying-a-release).

## Find Settings

Settings is the last item in the ⋯ menu of every room. There you see whether notifications work, and you can send a test notification. A line about the lock screen, saying that it shows titles only if your phone allows sensitive content there, is shown only when notifications are on.

## Disconnect a phone

Choose "Disconnect this phone" in Settings. If you have lost the phone, revoke it from the server instead. The app then has to start again from pairing the next time it contacts the server.

## The phone's connection

When pairing, the phone gets its own credential that is valid for that phone only. It can be revoked and lasts 30 days unless you set something else. As long as you use the app it renews itself.

## Language

The app's language is its own setting and does not follow the phone's language. Swedish is the default. You choose Svenska or English on the pairing screen or in Settings. [Read more about languages](../reference/languages.md).

## License in the app

Without a license key, the Today widget shows a small coin as a reminder that this is the free version. You enter a key at the bottom of Settings. [Read what the key does](../explanation/licensing.md).
