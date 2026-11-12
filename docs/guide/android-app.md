# The Android app

[Svenska](android-app.sv.md)

<!-- description: The Android app shows Work, Journal and Shopping from the same server as Claude. What the app does, what it does not do, and how to get started. -->

The Android app is a second surface for the same Sidekick server, next to Claude. It shows the same records from the same database. There is no prebuilt APK: you build the app from the source code.

:::note[Preview]
The app is built and tested automatically, including on an emulator. It has not been tried on a real phone against a real server.
:::

## What the app does

- **Work:** today's agenda, projects, tasks and steps. You can read them, check them off and reopen them.
- **Shopping:** lists and items. You can add, edit, tick off and undo.
- **Journal:** read days and entries, and write or edit entries by hand.
- **The Today widget:** today's tasks on your home screen. [Read about the widget and reminders](today-widget.md).
- **Settings:** notification status, a test notification, the phone's connection and the option to disconnect the phone.

## What the app does not do

- It does not create tasks or projects. You do that in Claude.
- It runs no AI and does not talk to Claude.
- It does not show Contacts or Control.
- It has no QR scanner and does not ask for the camera.
- It does not back up its connection or transfer it to a new phone.

There is no iOS app.

## What you need

- A phone with Android 7.0 or newer and an up-to-date Android System WebView, version 123 or newer.
- A Sidekick server that the phone reaches over HTTPS at a public address.
- A computer where you can build the app.

The work-laptop package has no route to a phone.

## Get started

1. Build the app and install it on the phone.
2. Turn on the app's connection on the server.
3. Create a pairing code on the server. The code works once and for ten minutes.
4. Open the app, enter the server's address and the code, and tap Connect.

Every command is in the operations guide. [Read how to build, install and pair the Android app](../operate/pair-android.md).

## Find Settings

Settings is the last item in the menu of the Work room. There you see whether notifications work, and you can send a test notification.

## Disconnect a phone

Choose "Disconnect this phone" in Settings. If you have lost the phone, revoke it from the server instead. The app then has to start again from pairing the next time it contacts the server.

## The phone's connection

When pairing, the phone gets its own credential that is valid for that phone only. It can be revoked and lasts 30 days unless you set something else. As long as you use the app it renews itself.

## Language

The app's language is its own setting and does not follow the phone's language. Swedish is the default. The language is chosen when the app is built. [Read more about languages](../reference/languages.md).

## License in the app

Without a license key, the Today widget shows a small coin as a reminder that this is the free version. You enter a key at the bottom of Settings. [Read what the key does](../explanation/licensing.md).
