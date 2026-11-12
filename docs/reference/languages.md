# Languages in the rooms, the app and the server

[Svenska](languages.sv.md)

<!-- description: The rooms and the Android app each have their own language setting, with Swedish as the default and English as the alternative. This page also covers which language the server's commands use. -->

The rooms and the Android app each have their own language setting, with Swedish as the default and English as the alternative. This page also covers which language the server's commands use.

## The rooms

The texts in the rooms are Swedish by default (`SIDEKICK_MCP_APP_LOCALE=sv`). Set `SIDEKICK_MCP_APP_LOCALE=en` on the server for English.

## The work package

Every `tools/work.sh` command prints Swedish or English: `SIDEKICK_WORK_LANG=sv|en`, else `SIDEKICK_WORK_LOCALE` in
`work.env`, else the system `LANG`. That is a separate choice from the language of the apps and of Hindsight's answers,
which is `SIDEKICK_WORK_LOCALE` in `work.env`: the first run copies `sv` from the template, and the guide changes it only
if the value is missing. Set `SIDEKICK_WORK_LOCALE=en` there, then run `bash tools/work.sh start`, for English app texts.

## The Android app

The app's language is its own setting, never the system language: Swedish by default, English as an
alternative. You choose it in the app itself, on the pairing screen or later in Settings (Inställningar); the choice is kept in the app's own
storage and survives a restart. The `sidekick-app-locale` meta tag in `frontend/mobile.html` (`sv` or `en`) only sets the language the app starts in before
you have chosen, so nothing needs rebuilding for English. The pairing screen, the widget and the reminder notification texts follow the same language.
The one exception is the widget picker's names and previews, which follow the phone's language. The pairing command's own messages follow `SIDEKICK_MCP_APP_LOCALE`.
