# ADR-005: An official Android app that reuses the MCP Apps rooms

- Status: Accepted (D-075, 2026-11-08); implemented. Revised 2026-11-10 to describe the delivered
  architecture, and corrected 2026-11-11 (the companion routes exist only when `SIDEKICK_COMPANION_ENABLED=true`); the
  decision is unchanged. Amended 2026-11-15 (D-095): the app may also create and edit Work records; see
  "Amendment 2026-11-15" below. Amended 2026-11-24: Start and the suggestion inbox on the phone; see
  "Amendment 2026-11-24" below.
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

## Amendment 2026-11-15: writing from the app (D-095)

The decision above kept the app to reading and checking off, with everything else created through
Claude. The owner changed that line. The app now has quick forms that create and edit, as a fallback
for the moments the owner cannot talk to Claude: in a meeting, on a bus, anywhere quiet. Claude stays
the main way in, and the app still has no model, assistant or voice pipeline of its own.

What the app may write, all through `/companion/v1/` and the same use cases as the MCP tools:

- **Tasks**: create a task (title, optional due date, optional place and note) and edit one (title,
  note, due date, place, priority); a place is a project, a process or a domain. `POST /companion/v1/tasks` and
  `POST /companion/v1/tasks/{task_id}/update`; completing and reopening keep their own routes.
- **Journal entries**: write and edit the owner's own entry by hand. These routes already exist
  (the journal room, D-076) and are unchanged.
- **Projects**: change a project's title, status, description and start and target dates.
  `POST /companion/v1/projects/{project_id}/update`.
  Creating, moving or restructuring projects, domains and processes stays with Claude.

Rules that do not change: the device holds capabilities, not application scopes. The new
capability `companion:work:write` maps to the fixed scopes of exactly these three operations
(`backend/src/sidekick/companion/operations.py`), and each answers with the record it wrote, so it also
needs `companion:tasks:read`. A device paired before this change gets it with
`python -m sidekick.companion.cli grant --scope companion:work:write` (it is part of the `app` preset). Every write
carries an `Idempotency-Key` and, for an edit, the record's version; a stale version is a conflict and
is never rebased. The request bodies name only the fields the form can change, and the ingress
allowlist gains exactly these three method and path pairs. The app reuses the Work room's own forms
(the + in the tabs, the task's edit menu, the due-date and place choices, the project's edit form);
`CompanionRoomTransport` answers only the fields the routes take, so a control for tags, repeat rules or
estimates stays hidden on the phone, as before. A write that gets no answer fails visibly, the form keeps
what was typed, and the retry reuses the first idempotency key, so nothing is written twice. A write that gets no
answer because of the connection is kept in the phone's outbox instead (see "Offline writes" below).

### Deleting and the trash

The app also moves a task, a journal entry or a shopping item to the trash and takes it back, with an
Undo right after (the same use case as the MCP tools `move_to_trash` and `restore_from_trash`), and has
a trash screen in its settings. Moving to the trash and restoring add no device capability: each
route needs the write and read capability of its room (`companion:work:write` with `companion:tasks:read`,
`companion:journal:write` with `companion:journal:read`, `companion:shopping:write` with
`companion:shopping:read`), so a device that may write in a room may trash and restore there, and a device
paired earlier needs no grant. The routes are
`POST .../tasks/{id}/trash`, `.../untrash`, the same pair for journal entries and shopping items, and
`GET /companion/v1/trash`, which lists only the kinds the device may trash. No route reaches a project,
a domain, a process, a contact or a step.

Permanent removal stays out of MCP (D-031) and is not a general capability here either. The app may
remove a task that is already in the trash (`POST .../tasks/{id}/erase`) or empty the trash of tasks
(`POST /companion/v1/trash/empty`). Both need a capability of their own, `companion:work:erase`, besides
`companion:work:write`, because they cannot be undone. `--preset app` includes it for new pairings; a device
paired earlier does not get it and keeps trashing and restoring until the owner runs
`grant --scope companion:work:erase`. `GET /companion/v1/trash` tells the phone with `can_erase` whether
the device holds it, and the trash screen then shows no "delete for good" and no "empty" without it; the
server refuses both with 403 either way. They also need an explicit confirmation: the request body must carry
`confirm: true`, the transport refuses to send it without the trash screen's own yes, and the use case
still accepts only a trashed record at its current version. A journal entry and a shopping item can never
be removed this way: the application role has no DELETE on their tables, so they can only be restored.
A task that still has steps or links stays, and the answer counts it as kept. A delete needs the network
and is not queued in the outbox.

### Share to Sidekick (issue 23)

The app is also a share target for plain text and links (`ACTION_SEND`,
`text/plain`; no pictures or files). A small sheet shows the shared text and an editable title, and the owner chooses
between a task and a new entry in today's journal; nothing is written before Save. The sheet writes through the
same two tools as the rooms' forms (`create_task`, `write_journal_entry`), so it needs no new route, scope or
capability, and it follows the same rule as the forms: no answer means a visible failure that keeps the text and
retries with the same idempotency key. The shared text lives only in memory until the sheet closes; when no answer
comes, the sheet's task or journal write is kept in the outbox like any other (see "Offline writes" below) and the sheet
says it is waiting for the network.

### Offline writes (2026-11-15)

The owner decided that what is created or edited in the app without a network waits on the phone until it reaches the
server, and that this changes the earlier rule that journal text is never stored on the phone.

- **Tasks and Projects.** A new task, an edit of a task and an edit of a project that get no answer because of the
  connection (`network` or `timeout`) are put in the same durable outbox as check-offs and shopping, with the
  idempotency key of the attempt that got no answer, so a request that did reach the server is replayed, never applied
  twice. The room is answered with a stand-in of the record (the edit laid over the record as last read, with the
  version unchanged; a new task under an id that is not a UUID and never reaches the server), and draws it as waiting
  ("Väntar…") until the server has taken it, after which the rooms read again. A second edit of a task or project that
  still waits, and has never been tried, is folded into the first (the later value of a field wins, a new key); in every
  other case it is refused visibly rather than dropped. An edit of a record the app has not read is not queued.
- **Final refusals are never silent.** A 409, 404, 410 or 422 does not discard the write: it stays in the queue as
  failed, the app says so in a card with the words the owner wrote, which can be copied, and the owner removes it or, if
  it can still succeed, tries again. A write older than seven days is kept the same way.
- **Journal text, encrypted.** A journal entry written or edited without a network, and a journal entry saved from the
  share sheet, wait in a second queue whose file is encrypted at rest with AES-256-GCM. The key is generated in the
  Android Keystore and cannot be exported. The text is never in the file, its temporary copy or a quarantined copy in clear
  text, never in a log or a crash report, and reaches the page only to be drawn as waiting. When the queue
  becomes empty (the server has confirmed the last entry, or the last refused one was removed by the user) its file and
  the Keystore key are removed; the next entry creates a new key. Both are also erased when the phone is unpaired. If the key is
  lost (a restored phone) the queue cannot be read and is moved aside; nothing is guessed. The queue is in the no-backup directory, so it never leaves
  the phone.
- **Not queued.** Moving to the trash, restoring and removing for good need the network, as above.

## Amendment 2026-11-24: Start and the suggestion inbox on the phone

The phone also shows Start and the inbox of suggestions from automations (ADR-013), for the moments the owner
cannot talk to Claude; Claude stays the main way in. The routes are `GET /companion/v1/start`,
`GET /companion/v1/suggestions` and `.../suggestions/{id}` for reading, and `POST .../suggestions/decisions`,
`.../suggestions/group-approvals` and `.../suggestions/{id}/undo` for deciding. Each calls the use case the MCP tool
of the same name calls (`get_start`, `list_suggestions`, `get_suggestion`, `decide_suggestions`,
`approve_suggestion_group`, `undo_suggestion`), so the phone reads what Claude reads and writes through the same
transaction, idempotency record and audit event.

- **Three capabilities.** `companion:start:read` (with `companion:tasks:read`, because Start reads across rooms) and
  `companion:suggestions:read` are part of `--preset app`. `companion:suggestions:decide` is not: it applies a card's
  effect (it creates a task or a contact), so it is its own capability, named explicitly at pairing or with
  `grant --scope companion:suggestions:decide`, and always needs `companion:suggestions:read` besides. A device paired
  earlier keeps what it had until the owner grants it.
- **The owner decides.** Deciding is the owner's act. In Claude a group is approved only by the app, proved by a decision
  ticket. The phone has no ticket; the device capability, its key binding and the use case's own check of the group
  digest the owner was shown take its place. A group that changed since it was shown is refused as a whole.
- **Channel, idempotency and audit.** The use case records the decision channel `companion` on the card (`decided_by`
  stays `you`), never `model`. Every write carries an `Idempotency-Key`, and the channel is part of what the key
  stands for, so a replay answers with each card as it is now and a key reused on another channel is refused.
  One call decides one to three cards; the owner is always the credential's, never named in the body.
- **No editing.** The phone approves or dismisses a card as written. The request bodies name no `edits`, so a card's
  payload cannot be changed from here; that stays in the app in Claude.

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
- Tests: `backend/tests/api/test_companion*.py`, `frontend/tests/mobile/mobile-companion-transport.test.ts`,
  `frontend/android/app/src/test/kotlin/com/roadlake/sidekick/`.
- Related decisions: D-052, D-075, D-077 to D-084 in the [decision log](../log.md).
