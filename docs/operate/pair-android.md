# Build, install and pair Android

[Svenska](pair-android.sv.md)

<!-- description: Download the signed Android app or build it from source, install it and connect the phone to your server with a one-time code. -->

Download the signed Android app or build it from source, install it and connect the phone to your server with a one-time code.

## What the app does and does not do

The app is a second surface for the same Sidekick server, next to Claude. It talks to the server's
companion routes under `/companion/v1/` and to nothing else.

It does not create tasks or projects, run AI, or talk to Claude: those happen in Claude. It has no QR
scanner and no camera permission: the pairing code is typed, pasted, or arrives through a pairing link. It does not back up or transfer
its credential (`android:allowBackup="false"`). It runs on Android 7.0 or newer (`minSdk` 24).
Android 13 and newer ask for notification permission once, after pairing. There is no iOS app.

## Download the signed app

Every release on the repository's GitHub Releases page has a signed `sidekick-X.Y.Z.apk`, built and signed by the
release workflow with the maintainer's key, next to `SHA256SUMS` and its signature (`SHA256SUMS.sigstore.json`).
Download the APK and those two files, check them as described in
[Verifying a release](../maintainers/release.md#verifying-a-release) (`sha256sum -c SHA256SUMS`, then
`cosign verify-blob` and `apksigner verify --print-certs`), and go on to [Install](#install). Later releases install
over it, because they are signed with the same key. You can also build the app yourself, as below. A self-built app
has another key, so it cannot update the downloaded one or the other way round: uninstall the old one first and pair
again.

## Build it yourself

### Requirements

| Tool | Version | Source |
| --- | --- | --- |
| JDK | 21 (CI uses Temurin 21; the Kotlin target is JVM 21) | `.github/workflows/ci.yml`, `frontend/android/app/build.gradle` |
| Android SDK | Platform 36 (`compileSdk` and `targetSdk` are 36) | `frontend/android/variables.gradle` |
| Node.js | 22 (CI pins 22.23.4) with npm 10 | `.node-version`, `frontend/package.json` |
| Gradle | 8.14.3, downloaded by the wrapper (`./gradlew`) | `frontend/android/gradle/wrapper/gradle-wrapper.properties` |

Point Gradle at the SDK with `ANDROID_HOME`, or with `sdk.dir=<path>` in a file named `local.properties` in the `android` folder of the frontend
(that file is git-ignored). The first build downloads Gradle and the Android and Kotlin dependencies from
Google's and Maven Central's repositories, so it needs internet access.

### Minimum WebView

The app's screens are a web page shown in Android System WebView, which updates separately from Android. `minSdk` 24
does not say which WebView you have, so the app states its own floor: **Android System WebView (Chromium) 123 or
newer**. 123 is the first version with the CSS `light-dark()` function that the screens use natively. The same number
is the `target` and `cssTarget` of the mobile build (`frontend/vite.mobile.config.ts`; the app has no browserslist),
`MIN_CHROMIUM_MAJOR` in `WebViewRequirement.kt` and `minWebViewVersion` in `frontend/capacitor.config.ts`;
`WebViewRequirementTest` fails if they differ. At start the app reads the installed WebView version. If it is older, the
app shows a short explanation (Swedish or English, per the app's language setting) instead of a blank screen. To fix it,
update Android System WebView and Google Chrome in the app store. If the version cannot be read, the app starts as usual.

### Build

Run from the repository root. The web part (the mobile bundle) is built first, then Capacitor copies it
into the Android project and generates the plugin module, then Gradle builds the app.

```bash
cd frontend
npm ci
npm run build:mobile          # writes the bundle to dist-mobile
npx cap sync android          # copies dist-mobile into the Android project
cd android
./gradlew assembleDebug
```

The debug APK is `app/build/outputs/apk/debug/app-debug.apk` inside `frontend/android`.

The build ends in `frontend/android`. Go back to the repository root (`cd ../..`) before the server commands
below that use `uv --project backend`.

Repeat `npm run build:mobile` and `npx cap sync android` after every change to the web code; Gradle alone
does not rebuild it. `./gradlew test` runs the JVM unit tests that CI runs.

Debug and release builds have different application ids (`com.roadlake.sidekick.debug` and `com.roadlake.sidekick`), so
they are separate installs and each one has to be paired. The debug build is signed with the standard
Android debug key. It also accepts plain `http` to `10.0.2.2`, `localhost` and `127.0.0.1` so an emulator
can reach a server on the same machine; every other address must be `https`, and the release build accepts
nothing else.

**Release.** The repository contains no signing configuration and no key. `./gradlew assembleRelease`
produces an unsigned APK; sign it with your own key and keep that key outside the repository. Publishing to
an app store is not covered here.

## Install

- **adb**: enable developer options and USB debugging on the phone, connect it, then
  `adb install -r sidekick-X.Y.Z.apk` for the downloaded app, or `adb install -r app/build/outputs/apk/debug/app-debug.apk` (from `frontend/android`) for your own debug build.
- **Sideload**: copy the APK to the phone and open it. Android asks you to allow installs from the app that
  opened the file ("install unknown apps"), and Play Protect may warn about an unknown developer.

For reminders, also install a UnifiedPush distributor. The one this app is built and tested with is the
**ntfy** Android app. Open it once after installing. On recent Android versions, set its battery use to
unrestricted, or wake-ups can be delayed.

## Server: what has to be on

The companion routes are off by default and are not even on the public surface until you enable them
(`backend/src/sidekick/shared/config/`, `companion_enabled`; `backend/src/sidekick/api/public_surface.py`).

The routes, their parameters, request bodies, the device capability each one checks and the closed list of refusals are
published as an OpenAPI 3.1 document, [`contracts/companion-api.generated.json`](../../contracts/companion-api.generated.json),
generated from the registered routes (`python -m sidekick.api.export_companion_contract`); CI fails when it is stale. A
successful answer is the structured content of the MCP tool of the same name
([`contracts/mcp-tools.generated.json`](../../contracts/mcp-tools.generated.json)).

| Variable | Needed for | Default |
| --- | --- | --- |
| `SIDEKICK_COMPANION_ENABLED=true` | Pairing and the whole app. Restart the API after changing it. | `false` |
| `SIDEKICK_PUSH_ENABLED=true` | Queuing and sending reminders. Set it on the API **and** the push worker. | `false` |
| `SIDEKICK_PUSH_ALLOWED_HOSTS` | Hosts a phone may register as its push endpoint. Add your own ntfy host here. | the public ntfy server |
| `SIDEKICK_PUSH_AUTH_HOST` and `SIDEKICK_PUSH_AUTH_TOKEN` | Only for an own ntfy server that needs a token to publish. The host must also be in the allowlist. | unset |
| `SIDEKICK_OWNER_TIMEZONE` | The zone for "today", the summary time and the quiet hours. | the built-in default |
| `SIDEKICK_PUSH_SUMMARY_TIME`, `SIDEKICK_PUSH_DUE_LEAD_MINUTES`, `SIDEKICK_PUSH_QUIET_START`, `SIDEKICK_PUSH_QUIET_END` | When reminders fire. | 08:00, 15 minutes, 21:00, 07:00 |
| `SIDEKICK_ENABLED_ROOMS` | Which rooms the server (and so the app) shows. | every room |

The phone must reach the server over **HTTPS** at a public address, the same kind of address Claude uses for
the connector (see the self-hosting guide below). The example Caddyfile in `deploy/selfhost/` already forwards the exact companion paths, and the API answers
them with a plain 404 until the flag is on.

For a self-hosted installation, set these in `selfhost.env` and see
[First start on a server](../start/self-hosted-server.md). The Work laptop package pins the companion and
push off on purpose and has no phone route.


## On a self-hosted server

On a self-hosted server the server steps are, in order:

1. In `selfhost.env` set `SIDEKICK_COMPANION_ENABLED=true`, then recreate the API:
   `docker compose --env-file selfhost.env up -d --force-recreate api`.
2. Print a pairing code (it works once, for 10 minutes; the rights it prints are what the phone will have):

   ```bash
   docker compose --env-file selfhost.env exec -T api python -m sidekick.companion.cli pair --label "My phone" --preset app
   ```

3. In the app, enter your server's address (`https://<your-domain>`, nothing after the host) and the `rspair_...` code
   from the JSON on standard output.

For reminders on the phone also set up push: see "Push reminders" in [Push reminders](push-reminders.md)
(`--profile push`, and `sh ntfy-init.sh` for the own ntfy server).

## Pair a phone

Pairing is a one-time, operator-run step. The command prints a code that the phone swaps for its own
credential; you never see that credential.

From a checkout (development or any host that has the backend environment), run from the repository root:

```bash
uv run --project backend python -m sidekick.companion.cli pair --label "My phone" --preset app \
  --server-url https://sidekick.example.com
```

`--server-url` is the address the phone reaches the server on (scheme and host, nothing after; `https` only, and
`http` only for `localhost`, `127.0.0.1` and `10.0.2.2` in development). It is optional: with it the command also
prints a pairing link (see below).

For a self-hosted installation, run the same module inside the running API container, from
`<repository>/deploy/selfhost` (where `selfhost.env` is). `-T` keeps standard output clean, so the JSON is not mixed
with terminal output:

```bash
docker compose --env-file selfhost.env exec -T api \
  python -m sidekick.companion.cli pair --label "My phone" --preset app --server-url https://<your-domain>
```

What you get:

- On stderr, the rights the phone will have (in the language of `SIDEKICK_MCP_APP_LOCALE`), the time the
  code stops working, and the credential lifetime.
- On stdout, one JSON document. `pairing_secret` is the code (it starts with `rspair_`); it is shown only now.
  With `--server-url` it also has `pairing_link`: `sidekick://pair?server=<url-encoded address>&code=<code>`, and
  `pairing_check`, a six-digit check code such as `846 345` (also printed on stderr).

Notes:

- `--scope` or `--preset app` is mandatory; the command refuses to guess. `--preset app` grants tasks (read
  and complete), notifications, Shopping (read and write), Journal (read and write) and the license row. You
  can instead list `--scope companion:…` values (repeatable) for a narrower phone.
- The code works **once** and for **10 minutes** (`PAIRING_TTL` in `backend/src/sidekick/companion/service.py`).
- Without `--user-id <uuid>` the command uses the installation's only active owner and refuses if there is not
  exactly one.
- `--device-days N` (1 to 90, default 30) sets how long the phone's credential lasts.
- The code is plain text. There is no QR code: paste or type it into the app, or use the pairing link.
- The pairing link contains the code, so treat it like the code: send it only to your own phone (a note to
  yourself, a message to yourself) and do not share it. It stops working after one use or 10 minutes.

**Easiest: the pairing link.** Open the `pairing_link` on the phone (tap it in a message or note). Sidekick opens,
shows "Connect to <your server>?" and a **check code**, and connects only when you tap **Connect**; **Cancel** drops
the link. Compare the check code with the one `pair` printed when you created the code: if they differ, the link did
not come from your command, so tap **Cancel**. Nothing is paired by the link alone, because any app or page can open
such a link: connect only if you created the code yourself.

**Why the link is not a verified Android App Link.** An App Link (`https`, `android:autoVerify="true"`) proves to Android
that the app belongs to the domain in the link, through an `assetlinks.json` file on that domain that names the app's package and
signing-certificate fingerprint. That cannot work here: Android reads the domains an app may verify from its manifest at
build time, and every owner's domain is different, so the released app cannot name yours (a wildcard cannot be verified),
and a build of your own would have to list your domain and be signed with your own key. A fixed `roadlake.com` route
would not help either, because the link has to name your server, not ours. The app therefore uses its own scheme, `sidekick://pair`, and the protection is in the code and in the app instead:

- The code works once and for 10 minutes, and the server limits failed attempts per address. An app that captured the link
  after you had paired (or after 10 minutes) gets nothing.
- The link never pairs by itself. The app shows the server's host, "Connect to <host>?", and waits for your tap on
  **Connect**; a link that names a server you did not expect is refused with **Cancel**. A host with look-alike
  letters from another alphabet is shown in its ASCII form (`xn--…`).
- The app also shows a check code, six digits derived from the pairing code (the first four bytes of its SHA-256,
  modulo 1,000,000), and the server's `pair` command prints the same digits. A link written by someone else carries a
  code you never created, so its digits do not match the ones in your terminal. This catches the real attack on a
  self-hosted server, a link that points the phone at someone else's server, without a second step for you: you
  already have the terminal open. The check code is a comparison aid, not a secret, and it does not replace the host
  question: it proves that the code is yours, the host line shows where it will be used. Do not share the check code
  together with the link (the same message or screenshot), or it no longer shows that the link is yours. If the app
  cannot show the check code, it keeps **Connect** off and says so: pair by hand instead.
- The link is parsed strictly: exactly one `server` and one `code`, an `https` origin with no path, a code of the right
  shape, at most 1024 characters. Anything else is ignored.
- A link that reaches a phone that is already paired is dropped, and the app says so once.
- The manifest has one filter, for `sidekick://pair`, and no `https` filter; `WidgetResourcesTest` fails if another is added.
- If you do not want to rely on the link, use the pairing screen by hand: the code then never passes through another app.

What the scheme cannot prevent is another installed app that also registers `sidekick://pair` and is chosen by Android's
app picker (or is the only one), so that it reads the link before Sidekick does. Send the link only to yourself, check which app
opens, and if you doubt the phone, type the code by hand. The code is useless after its first use.

**By hand.** On the phone, open Sidekick. The pairing screen speaks the app's language (Swedish by default; see [Languages](../reference/languages.md#the-android-app)) and has a "Where do I find the code?" help line. It asks for:

1. **Server address**: the origin of your Sidekick server, for example `https://sidekick.example.com`. Nothing
   after the host: no path (not `/mcp`), no query, no login. If you leave out `https://` the app adds it.
2. **Pairing code**: the `rspair_…` string. Tap "Show code" to check what you pasted.

Tap Connect (or the keyboard's Go key on the code field). Each field shows its own error: an empty field, an
address that is not an `https` origin, a code that is too short or has characters a code never has. The app then asks
for notification permission (Android 13 and newer).

The Today widget is 4x2 cells by default (you can resize it). Before pairing it shows a "Connect Sidekick" message with
a **Connect** button that opens the app on the pairing screen.

### List, extend and revoke phones

```bash
uv run --project backend python -m sidekick.companion.cli list
uv run --project backend python -m sidekick.companion.cli revoke --device-id <id>
uv run --project backend python -m sidekick.companion.cli grant --device-id <id> --preset app
```

(Self-hosted: from `deploy/selfhost`, use the `docker compose --env-file selfhost.env exec -T api python -m sidekick.companion.cli …` form.) `list` prints each
device's `id`, label, rights, expiry, `revoked_at` and `last_used_at`; it never prints a secret. `revoke`
cuts the phone off and removes its push registration; the app returns to the pairing screen the next time it contacts the server. `grant`
only adds rights to an already paired phone (for example after you enable a room); it never removes any.
From the phone, Settings, "Disconnect this phone" does the same for that phone and clears it. Use `revoke` for
a lost phone.

### How long a credential lasts

A phone's credential lasts 30 days by default (`--device-days`, at most 90). In its last 7 days it renews
itself, without the owner doing anything: the app tries when it comes to the foreground and in the widget's
periodic background job, through `POST /companion/v1/device/renew`. Each renewal gives a new credential with
the full lifetime again. The old one keeps working for 10 minutes so a lost answer can be retried, and at most
5 renewals succeed per 24 hours. A phone that stays unused beyond its expiry has to be paired again with a
new code.

## Troubleshooting

| What you see (English text) | Likely cause and fix |
| --- | --- |
| "The address must start with https:// and include only the server…" | The address has a path, query or login, or uses `http`. Use the bare origin. `http` works only in the debug build, and only for `10.0.2.2`, `localhost` and `127.0.0.1`. |
| "That code doesn't look right." | The pasted code is cut off or has extra characters. Paste the whole `rspair_…` string. |
| "That code has expired or was already used. Create a new one." | The server answered 401 `pairing_invalid`: the code is older than 10 minutes, was used once already, or is wrong. Run `pair` again. |
| "Couldn't reach the server…" or "The server didn't respond." | Address typo, DNS, TLS certificate or tunnel problem, or no internet on the phone. Open your server's address in the phone's browser to test reachability and the certificate. |
| "Couldn't connect. Try again." | The server answered something else, most often 404 because `SIDEKICK_COMPANION_ENABLED` is not `true` (or the API was not restarted). |
| "Too many attempts. Wait a minute and try again." | The pairing endpoint allows each address 10 failed attempts per minute (30 for all addresses together, which only applies to addresses that failed recently), plus a small reserve of 3 attempts a minute for a valid code. Behind a tunnel or proxy all visitors share one address. Wait a minute. |
| "The connection has ended. Connect again." | The server refused the phone's credential (401): the phone was revoked, its credential expired, or the owner was deactivated. Pair again with a new code. |
| Settings: "Install the ntfy app to get notifications." | No UnifiedPush distributor is installed. Install ntfy and reopen Sidekick. |
| Settings: "Notifications are off for Sidekick." | Allow notifications for Sidekick in the phone's system settings. |
| Test: "Notifications are turned off on the server." | `SIDEKICK_PUSH_ENABLED` is not `true` on the API. |
| Test: "Notifications aren't set up yet." | The server has no push registration for this phone: the ntfy app is missing, permission is denied, or the endpoint host is not in `SIDEKICK_PUSH_ALLOWED_HOSTS` (the server answers 422 `endpoint_not_allowed`). |
| Test queued but nothing arrives | The push worker is not running, ntfy battery optimization is on, or the public ntfy server has hit its daily quota (the worker backs off and retries). |
| `pair`: "pass --user-id: there is not exactly one active owner" | The installation has zero or several active users. Pass `--user-id <uuid>`. |
| `pair`: "requires an explicit --scope … or --preset app" | Choose the rights explicitly. |
