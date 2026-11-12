# ADR-005: An official Android app that reuses the MCP Apps rooms

- Status: Accepted (D-075, 2026-11-08); implemented. Revised 2026-11-10 to describe the delivered
  architecture, and corrected 2026-11-11 (the companion routes exist only when `SIDEKICK_COMPANION_ENABLED=true`); the
  decision is unchanged.
- Date: 2026-11-08
- Owners: Sidekick application maintainers

For building, installing and pairing the app, see [the Android guide](../../operate/pair-android.md).

## Context

Sidekick's product UI is delivered as MCP Apps inside Claude (D-052). A phone needs a few things an
MCP host cannot give: a home-screen widget with today's tasks, reminders that arrive when Claude is
closed, and quick check-offs without starting a conversation. Sidekick is a forms-and-lists
application, not a graphics-heavy one, so a second, native implementation of every view would cost
far more than it would gain.

Constraints the decision had to respect:

- MCP Apps in Claude stay the primary surface, and no standalone web app or desktop shell returns
  (D-052, D-082).
- Business rules live once, in the backend use cases; transports are thin (ADR-002).
- The phone is a second client of the owner's self-hosted server, reached over public HTTPS.
- Using Sidekick is free and a license key only removes a purchase notice (D-083), so licensing must
  never gate any app function.
- iPhone is not shipped now, but the architecture should not make a later iOS app harder.

## Decision

Sidekick has an official Android app as its second product surface. It packages the same React rooms
that run in Claude in a Capacitor shell, talks to a dedicated, versioned companion adapter on the
server, and uses Kotlin only for what must be native.

### Shape of the app

```text
Shared React rooms + SidekickShell (frontend/src/features/mcp-apps)
  MCP entry    -> HostBridge (postMessage)  -> Claude -> curated FastMCP server (/mcp/)
  mobile entry -> CompanionRoomTransport    -> typed Capacitor plugin (Kotlin)
                                               -> native HTTP + encrypted pairing
                                               -> /companion/v1/ -> the same use cases
  Today widget (Glance) -> same native HTTP, cache and outbox ----------+
  Push wake (UnifiedPush) -> fetch reminders from /companion/v1/ -------+
```

- **One implementation per room.** Both entries mount the same room components through the
  `RoomTransport` seam (`frontend/src/features/mcp-apps/room-types.ts`). The mobile entry is
  `frontend/src/mobile/main.tsx`, built by `frontend/vite.mobile.config.ts` and packaged with the
  app; the app never loads its UI from the server.
- **A closed call list, not a generic executor.** `frontend/src/mobile/companion-transport.ts` maps
  a fixed list of room calls (for example `get_task`, `complete_task`) to named companion routes and
  returns the same structured result the MCP tool returns. Anything else fails before a request is
  sent. There is no `execute(tool, args)`, no caller-supplied URL and no MCP-to-HTTP loop.
- **Kotlin for native capabilities only** (`frontend/android/app/src/main/kotlin/com/roadlake/sidekick/`):
  the Capacitor plugin and HTTP client (`companion/`), the Keystore-protected pairing, the Today
  cache and completion outbox (`today/`), the Glance widget (`widget/`) and the UnifiedPush receiver
  and notifications (`push/`). The React side never sees the bearer credential.
- **Mobile-specific behavior stays in the shell.** The app has its own root view, Android Back
  handling and deep-link hints (`frontend/src/mobile/launch-hint.ts`: only Today or one task by id;
  anything else opens Today). Claude-only actions are hidden rather than faked, and the app has no
  model, assistant or voice pipeline of its own.
- **Rooms in the app:** Work (agenda, projects, tasks and steps; read, complete, reopen), Shopping
  and Journal (manual reading and writing, no AI). The server's `SIDEKICK_ENABLED_ROOMS` decides
  which rooms the app shows.

### Backend boundary: `/companion/v1/`

- A separate adapter (`backend/src/sidekick/api/companion.py`, `companion_rooms.py`,
  `companion_license.py`) over the existing application services. It is off unless
  `SIDEKICK_COMPANION_ENABLED=true`: while it is `false` (the default) the routes are not registered at all,
  and setting it to `true` registers them. They are kept out of the OpenAPI document either way.
- **Paired device credentials with their own purpose.** A phone is paired by an operator command
  (`python -m sidekick.companion.cli pair`) that prints a single-use code valid for ten minutes; the
  phone exchanges it for a device credential. Companion credentials are verified as their own token
  purpose (`backend/src/sidekick/shared/auth/service.py`): `/mcp/` refuses them, and a personal MCP
  token is never a companion credential.
- **Device capabilities, not application scopes.** A device holds only `companion:*` capabilities.
  Each route names one operation in `backend/src/sidekick/companion/operations.py`, which maps the
  capability to the fixed application scopes for that one call. For example, completing a task needs
  `tasks:write` inside `TaskService.complete`, but the device never holds `tasks:write` and cannot
  reach any other task write.
- **Every request is checked** for credential digest, purpose, expiry, revocation, active owner and
  capability. No route takes an owner id. Errors use one closed, versioned problem vocabulary that
  never echoes input or titles, and nothing logs a token, secret or title.
- **Writes are idempotent and versioned**: a completion carries the record's version and an
  `Idempotency-Key`, and a repeated request replays the stored result.
- **Credential lifetime** is 30 days by default, at most 90, and the device renews itself in the
  last seven days (D-077). Owners list, extend and revoke devices with the same CLI; a revoked
  device also loses its push registration.
- **Ingress** forwards only the exact companion method and path pairs
  (`deploy/selfhost/Caddyfile.example`); the rest of the server is not reachable from the phone.

### Offline: a bounded cache and outbox

The widget and the Today view share a native cache of today's tasks with a visible last-sync time.
There is a durable outbox only for reviewed task completion commands made from the widget
(`frontend/android/app/src/main/kotlin/com/roadlake/sidekick/today/Outbox.kt`): one entry per task, retried
with the original key and version, and dropped when too old. A conflict is never rebased
automatically. Journal and contact content is not cached. PostgreSQL stays authoritative.

### Push: content-free wake-ups through UnifiedPush

- The app uses UnifiedPush with the ntfy app as distributor (D-078). There is no Firebase/FCM and no
  Google services dependency. The self-hosting package ships a hardened ntfy server (D-080); the
  public ntfy.sh server works as a fallback.
- A domain change and its push intent are written in the same transaction
  (`backend/src/sidekick/companion/push_outbox_store.py`); a separate worker (`sidekick-push-worker`)
  sends only after commit, so a rolled-back change sends nothing and a failed push never rolls back
  a write.
- The push message carries no titles, ids, dates or user text. The phone treats it as an untrusted
  hint, fetches pending reminders from `/companion/v1/reminders/pending`, and shows the
  notification itself. Lock-screen visibility follows the phone's setting (D-079).
- Registered endpoints must be HTTPS on port 443 to an allowlisted host
  (`SIDEKICK_PUSH_ALLOWED_HOSTS`), which bounds the server-side request risk of sending to a
  device-supplied URL.
- Reminders are a morning summary and a reminder before a task's due time, with quiet hours
  (`backend/src/sidekick/companion/push_schedule.py`, `push_reminders.py`).

### License keys apply to both surfaces

One backend entitlement check serves Claude and the phone. The phone reads and sets the key through
`/companion/v1/license`; the key is verified offline against a public key (D-081, D-083). An invalid,
expired or missing key may show the purchase notice; it never disables tasks, the widget, push,
export or data access.

### Distribution, safety and verification

- The repository has no signing configuration or key. Automated builds produce debug APKs or
  unsigned release builds; signing happens outside CI with a key kept outside the repository.
  Distribution starts as a signed APK installed outside Google Play; a store listing is a later
  decision.
- The pairing record is encrypted with a non-exportable AES-GCM key generated in the Android
  Keystore (`companion/KeystorePairingStore.kt`). The app disables backup of its data
  (`android:allowBackup="false"`), never puts credentials in URLs, intents or widget state, and the
  release build accepts only HTTPS.
- No third-party analytics; no user content, tokens or endpoints in logs.
- CI builds the shared UI and the Android app and runs the Kotlin unit tests, the frontend tests and
  the backend companion tests (`backend/tests/api/test_companion*.py`).

### Delivery stages

Code comments refer to these stages:

| Stage | Content |
| --- | --- |
| M1 | Companion adapter, pairing and device lifecycle, Today view, Glance widget with offline completion; no push. |
| M2 | Push: subscriptions, transactional outbox, worker, reminders and credential renewal. |
| M3 | The rest of Work in the app: project list, projects, steps. |
| Later | Shopping and Journal rooms (`companion_rooms.py`). |

## Alternatives considered

| Alternative | Why not chosen |
| --- | --- |
| Kotlin/Compose UI, optionally with a Kotlin Multiplatform core | Rewrites every React room and leaves a third UI codebase for iOS. |
| Compose Multiplatform UI | Shares new Kotlin UI between Android and iOS, but duplicates the existing React UI. |
| Own WebView host with a hand-written Kotlin bridge | Same room reuse, but a later iOS app needs a second hand-written bridge; Capacitor already provides both. |
| React Native or Flutter | Neither renders the existing DOM-based rooms, so both mean a rewrite. |
| Firebase Cloud Messaging for push | Needs a publisher-owned project and a trusted sender, which for self-hosted servers means a central relay service. Deferred, not rejected. |

## Consequences

- Android is a supported surface with a second transport contract (`/companion/v1/`) and a native
  plugin contract to keep in step with the rooms. Contract tests guard the mapping.
- An installed APK cannot be assumed to upgrade together with a self-hosted server, so the
  companion contract is versioned in its URL and changes additively.
- The phone must reach the server over public HTTPS; a tunnel such as Tailscale Funnel counts as
  public HTTPS, not private-network authentication.
- Device binding of the credential (for example DPoP) is not implemented; a stolen credential is
  limited by its capabilities, its lifetime and revocation.
- A later iOS app can reuse the rooms and the companion contract through Capacitor, but still needs
  Swift for the Keychain, WidgetKit and a push adapter, and Apple's toolchain to build.

## Evidence

- Rooms and transports: `frontend/src/features/mcp-apps/room-types.ts`, `bridge.ts`,
  `sidekick-rooms.tsx`; `frontend/src/mobile/companion-transport.ts`, `sidekick-native.ts`.
- Android shell: `frontend/capacitor.config.ts`, `frontend/android/app/build.gradle`,
  `frontend/android/app/src/main/AndroidManifest.xml`, `frontend/android/variables.gradle`.
- Companion adapter and capabilities: `backend/src/sidekick/api/companion.py`,
  `backend/src/sidekick/companion/operations.py`, `backend/src/sidekick/companion/service.py`,
  `backend/src/sidekick/shared/auth/service.py`.
- Push: `backend/src/sidekick/companion/push_outbox_store.py`, `push_worker.py`, `push_schedule.py`;
  `deploy/selfhost/compose.yaml` (profile `push`).
- Tests: `backend/tests/api/test_companion*.py`, `frontend/tests/mobile-companion-transport.test.ts`,
  `frontend/android/app/src/test/kotlin/com/roadlake/sidekick/`.
- Related decisions: D-052, D-075, D-077 to D-084 in the [decision log](../log.md).
