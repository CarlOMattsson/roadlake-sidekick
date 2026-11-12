# Decision log

This is the public log of the product and architecture decisions that the code, tests and documents in this
repository refer to, for example as `D-083`. It is deliberately short. It is a summary, not a transcript: each
entry says what was decided and why, and the code and the [ADRs](adr/) are the maintained truth when they
differ. Decision IDs are stable and never reused. A decision that has been replaced
moves to the [archive](archive.md) and keeps its ID and its status there.

Status words: **Accepted** (in force), **Delivered** (built), **Superseded** (replaced; the entry names by
what, and lives in the archive), **Amended** (still in force but changed in part). Decisions were taken by the maintainer.

## Index

Replaced decisions (D-036, D-051, D-056, D-085, D-086) are in the [archive](archive.md).

| ID | Decision |
| --- | --- |
| D-004 | [One set of use cases for HTTP and MCP](#d-004---one-set-of-use-cases-for-http-and-mcp) |
| D-005 | [MCP tools are curated contracts](#d-005---mcp-tools-are-curated-contracts) |
| D-008 | [Tags and typed relationships are separate](#d-008---tags-and-typed-relationships-are-separate) |
| D-009 | [AI effects are bounded, and derived text is reviewed](#d-009---ai-effects-are-bounded-and-derived-text-is-reviewed) |
| D-013 | [Ingress and database share the self-host Compose project and observability stays outside it](#d-013---ingress-and-database-share-the-self-host-compose-project-and-observability-stays-outside-it) |
| D-031 | [Archive and trash are different; permanent removal is not an MCP tool](#d-031---archive-and-trash-are-different-permanent-removal-is-not-an-mcp-tool) |
| D-046 | [Claude is the primary assistant; Sidekick owns its data](#d-046---claude-is-the-primary-assistant-sidekick-owns-its-data) |
| D-052 | [No own product frontend; product UI is MCP Apps](#d-052---no-own-product-frontend-product-ui-is-mcp-apps) |
| D-053 | [Delivery follows MCP Apps coverage](#d-053---delivery-follows-mcp-apps-coverage) |
| D-054 | [Self-hosting is a product requirement](#d-054---self-hosting-is-a-product-requirement) |
| D-055 | [Commerce stays separate from product content](#d-055---commerce-stays-separate-from-product-content) |
| D-057 | [Small changes directly; destructive operations always confirmed](#d-057---small-changes-directly-destructive-operations-always-confirmed) |
| D-058 | [Tool replies carry the result JSON](#d-058---tool-replies-carry-the-result-json) |
| D-060 | [The host model may read the owner's own content](#d-060---the-host-model-may-read-the-owners-own-content) |
| D-061 | [Optional domain accent colour](#d-061---optional-domain-accent-colour) |
| D-062 | [Claude may move records to the trash after an explicit yes](#d-062---claude-may-move-records-to-the-trash-after-an-explicit-yes) |
| D-063 | [Owner time zone](#d-063---owner-time-zone) |
| D-064 | [Proposal and revert tools removed from MCP](#d-064---proposal-and-revert-tools-removed-from-mcp) |
| D-065 | [Claude writes the daily journal summary](#d-065---claude-writes-the-daily-journal-summary) |
| D-066 | [Claude may edit an existing journal entry](#d-066---claude-may-edit-an-existing-journal-entry) |
| D-067 | [Saved work views are app-only for now](#d-067---saved-work-views-are-app-only-for-now) |
| D-068 | [Shopping items can be trashed](#d-068---shopping-items-can-be-trashed) |
| D-072 | [Voice mode works through MCP](#d-072---voice-mode-works-through-mcp) |
| D-075 | [Official Android app as second surface](#d-075---official-android-app-as-second-surface) |
| D-076 | [AI-first: manual controls may be retired](#d-076---ai-first-manual-controls-may-be-retired) |
| D-077 | [Companion device token lifetime](#d-077---companion-device-token-lifetime) |
| D-078 | [Push through UnifiedPush](#d-078---push-through-unifiedpush) |
| D-079 | [Lock-screen reminders follow the phone](#d-079---lock-screen-reminders-follow-the-phone) |
| D-080 | [Own ntfy server is the intended push server](#d-080---own-ntfy-server-is-the-intended-push-server) |
| D-081 | [Offline license keys](#d-081---offline-license-keys) |
| D-082 | [Remove the old web shell](#d-082---remove-the-old-web-shell) |
| D-083 | [License: Roadlake Sidekick Source Available License](#d-083---license-roadlake-sidekick-source-available-license) |
| D-084 | [Remove the old chat engine](#d-084---remove-the-old-chat-engine) |
| D-088 | [Experimental voice entrance and direct probe removed](#d-088---experimental-voice-entrance-and-direct-probe-removed) |
| D-089 | [Persistence is PostgreSQL behind least-privilege roles](#d-089---persistence-is-postgresql-behind-least-privilege-roles) |
| D-090 | [Credentials are keyed digests; scopes are enforced in the use cases](#d-090---credentials-are-keyed-digests-scopes-are-enforced-in-the-use-cases) |
| D-091 | [Memory is derived and optional](#d-091---memory-is-derived-and-optional) |
| D-092 | [One curated public MCP surface](#d-092---one-curated-public-mcp-surface) |
| D-093 | [One error tree rooted at SidekickError](#d-093---one-error-tree-rooted-at-sidekickerror) |

### D-004 - One set of use cases for HTTP and MCP

Status: Accepted.
FastAPI routes and FastMCP tools call the same application use cases. An MCP handler never calls Sidekick's own
HTTP API. Why: one place for business rules, authorization and idempotency, so the two surfaces cannot drift.

### D-005 - MCP tools are curated contracts

Status: Accepted.
Each MCP tool has an explicit schema, annotations, bounded output, authorization and durable idempotency for
writes. There are no tools generated from routes and no generic "execute" or "query" tools. Why: a model
should see a small, reviewable and stable surface rather than the whole API.

### D-008 - Tags and typed relationships are separate

Status: Accepted.
Tags are a flat vocabulary; semantic relationships between records are typed and enforced by PostgreSQL
integrity. There is no arbitrary polymorphic string/ID graph and no graph database. Why: referential
integrity and simple queries beat a generic graph.

### D-009 - AI effects are bounded, and derived text is reviewed

Status: Amended. The generic propose, review, commit flow was removed with the chat engine (D-064, D-084).
Today MCP tools are direct commands: the server checks owner, scope, observed version and idempotency on every
call, and a model never owns the actor, the permissions or an unrestricted sequence of mutations. The review
step that remains is the journal draft: a draft derived by analysis is read, edited, rejected or finalised by
the owner through `get_journal_draft`, `update_journal_draft`, `reject_journal_draft` and
`finalize_journal_draft`. Why: the owner stays in control of what becomes a journal record.

### D-013 - Ingress and database share the self-host Compose project and observability stays outside it

Status: Accepted.
Central ingress (Caddy) and PostgreSQL run as services of the self-host Compose project in
`deploy/selfhost/`, each on its own concern-specific network (`data` and `push` are internal), and no
internal port is public. Observability stays outside that project. Why: a smaller blast radius and a
clear ownership boundary.

### D-031 - Archive and trash are different; permanent removal is not an MCP tool

Status: Delivered (partial); the HTTP part was removed by D-082.
Archiving keeps a record readable and linkable. Trash is a recoverable state with its own restore. Permanent
removal accepts only a record already in the trash and has no MCP tool. It was once a confirmed owner action
over HTTP; since D-082 removed those routes, the application method exists but no public surface (MCP or
companion) exposes it. MCP offers `list_trash`, `move_to_trash` and `restore_from_trash`. Journal sources are
immutable and cannot be trashed. Why: nothing a model calls may delete data for good. Retention and further
detail surfaces remain open.

### D-046 - Claude is the primary assistant; Sidekick owns its data

Status: Accepted.
Claude is the primary assistant platform. Sidekick remains the independent owner of its data, application
logic, history, derived memory and specialized tools, and prefers official Claude integrations over
duplicating general chat, voice or orchestration. Why: use the strongest assistant without giving up
ownership of the records.

### D-052 - No own product frontend; product UI is MCP Apps

Status: Accepted; amended by D-075 and ADR-005.
All product UI is delivered as MCP Apps inside Claude or another verified compatible host. A standalone web
app and a desktop shell are rejected as targets, and React components are reused only inside Apps. The
native Android app was added as a second surface by D-075. Why: one maintained UI instead of a thin client,
and the host provides the conversation, voice and identity.

### D-053 - Delivery follows MCP Apps coverage

Status: Accepted direction.
Delivery order is set by proving coherent navigation, editing and review in real remote Claude and mobile
hosts early, then covering every domain and the owner controls. A missing app path needs a reviewed
authorization contract, not a generic executor or a permanent own-UI fallback.

### D-054 - Self-hosting is a product requirement

Status: Accepted requirement; implementation continues.
Removing the own frontend does not remove packaging: a customer must be able to run Sidekick on their own
server or an always-on home computer with guided DNS/TLS/auth, updates, backup and recovery. The aim is to
run a signed release image without building from source; until a release image is published, the package
builds the image locally (`--build`). Only the own product UI is retired. See `deploy/selfhost/`.

### D-055 - Commerce stays separate from product content

Status: Conditional; policy open.
Any hosted checkout or customer-portal integration is evaluated as an optional layer. A billing record is not
an MCP identity, and a commerce provider never receives Work, Contact or Journal content.

### D-057 - Small changes directly; destructive operations always confirmed

Status: Accepted; the autonomy setting is no longer exposed (the Control room has no tool for it).
Smaller changes are applied directly. For destructive operations the tool description tells Claude to ask the
owner and wait for an explicit yes in that turn before it calls `move_to_trash`. That is an instruction to the
host model, not a check the server can make: the server enforces owner, scope, observed version and
idempotency, and keeps the action reversible (trash, never permanent removal). Why: the cost of a wrong small
change is low, and nothing a model calls can delete data for good.

### D-058 - Tool replies carry the result JSON

Status: Accepted; the model-text part is replaced by D-060.
The text part of an MCP tool reply contains the result JSON, because the host model reads only that part and
needs the ids. Logs, audit records, SQL telemetry and error surfaces never contain journal text or other user
content; that rule is unchanged.

### D-060 - The host model may read the owner's own content

Status: Accepted (replaces the model-text rule of D-058).
Within the token's scopes and for the signed-in owner's own data, the host model (Claude) may read journal
text and titles, contact addresses and other fields without the owner asking each time. Scopes and owner
filtering apply unchanged. Logs, audit, SQL telemetry and errors still never contain user data. Sidekick's own
gateways toward other model providers are not changed by this. Why: the assistant the owner is already
talking to needs the content to be useful.

### D-061 - Optional domain accent colour

Status: Delivered.
A domain has an optional colour from a closed list of eight names (`slate`, `blue`, `teal`, `green`, `amber`,
`orange`, `rose`, `violet`), never a free hex value. Each name maps to tokens that follow the host theme and
meet contrast limits (4.5:1 text, 3:1 border) in light and dark. The colour is never the only signal.
The name list is a contract: extend it with a new CHECK, never change a meaning.

### D-062 - Claude may move records to the trash after an explicit yes

Status: Accepted (maintainer decision, 2026-10-28).
`move_to_trash` is visible to the model and marked `destructiveHint`. Its tool description tells Claude to ask the
owner and wait for an explicit yes in the same turn before it calls the tool. The trash is a soft delete that
`restore_from_trash` reverses. A confirmation card was not chosen. This applies D-057 to the trash. Why: a model
may tidy up only after a clear yes, and nothing it moves is lost for good.

### D-063 - Owner time zone

Status: Accepted.
The owner's time zone is an installation setting (`SIDEKICK_OWNER_TIMEZONE`, default `Europe/Stockholm`). The
agenda and the journal compute "today" in that zone, and a date without a time means 23:59 local time.
Why: "today" must match the user's day, not UTC.

### D-064 - Proposal and revert tools removed from MCP

Status: Accepted; changes [D-056](archive.md#d-056---owner-review-of-proposals-over-mcp-historical) for the MCP surface.
`list_pending_proposals`, `get_proposal`, `list_revertible_actions`, `confirm_proposal`, `reject_proposal` and
`revert_assistant_action` are not part of the MCP surface.

### D-065 - Claude writes the daily journal summary

Status: Accepted.
The day summary is written by Claude through the tool `set_daily_journal_summary`. Sidekick does not add its
own AI provider for it.

### D-066 - Claude may edit an existing journal entry

Status: Accepted.
`update_journal_entry` is visible to the model, so Claude can change today's journal entry when the owner asks to add
to it. The entry is versioned, and such a change counts as a small change under D-057. A new entry per conversation
was not chosen. Why: the day stays one entry that the owner can keep adding to.

### D-067 - Saved work views are app-only for now

Status: Accepted.
The saved-view tools (`list_saved_work_views`, `create_saved_work_view`, `update_saved_work_view`,
`archive_saved_work_view`, `restore_saved_work_view`) carry `visibility=["app"]`, so the model does not see them.
There is no `view_id` on the board or the agenda yet. Why: the tools are easy to open to the model later; they are
harder to withdraw once a model depends on them.

### D-068 - Shopping items can be trashed

Status: Accepted; delivered by migration 044.
Shopping items get their own trash kind and follow the same rules as other records: soft deletion with
restore, and its tool description tells Claude to ask and wait for an explicit yes before using it.

### D-072 - Voice mode works through MCP

Status: Accepted.
Claude in voice mode sends MCP calls to Sidekick and this has been verified by the maintainer, so journaling by
voice rests on a confirmed capability. Voice needs no cards: the first line of a tool reply is one speakable
sentence (counts and names, no ids, versions or timestamps); ids and versions follow on later lines, where the
model still finds them for the next call.

### D-075 - Official Android app as second surface

Status: Accepted; amends D-052. See [ADR-005](adr/ADR-005-native-android-app.md).
Sidekick gets an Android app that reuses the MCP Apps React rooms in a thin native shell, with a Today task
widget and push after the first release. MCP Apps in Claude remain primary; a standalone web app and desktop
shells remain rejected. Native capabilities use Kotlin, and iOS is prepared for but not shipped.

### D-076 - AI-first: manual controls may be retired

Status: Accepted; the parity condition is replaced by D-082.
Manual controls that exist only in old views may disappear when Claude can do the same through the connector.
Journal writing and editing by hand stays available in the Journal room. Owner export is a tested server
command, not an MCP tool.

### D-077 - Companion device token lifetime

Status: Accepted; renewal delivered.
The Android companion token (`/companion/v1`) is valid for 30 days by default (at most 90), set when the
device is paired with `sidekick.companion.cli pair`. The device renews its own credential in the last seven
days before it expires (`POST /companion/v1/device/renew`); the replaced credential keeps working for ten
minutes and at most five renewals succeed per 24 hours. A device that lets it lapse pairs again. Binding the
credential to the device remains planned.

### D-078 - Push through UnifiedPush

Status: Accepted; the server choice is amended by D-080.
Android push uses UnifiedPush with ntfy as distributor. Visible reminders (a morning summary and a reminder
before a due time, with quiet hours) are included from the start. A push message never carries content: the
phone fetches the content itself. The server is replaceable.

### D-079 - Lock-screen reminders follow the phone

Status: Accepted.
Notifications use private visibility with a public version that shows only a count ("Sidekick - N reminders").
If the user hides sensitive content the count is all that shows; otherwise title and time are shown. The app
does not force titles to be hidden.

### D-080 - Own ntfy server is the intended push server

Status: Accepted; changes the server choice in D-078.
The package ships a hardened ntfy server (Compose profile `push`): pinned version, deny-by-default access so
only Sidekick sends and only the paired phone reads, no attachments, messages cached in memory for two hours
and never written to disk, a daily limit of 2,000 messages as a runaway guard, public only over HTTPS. The
shipped configuration still allows only ntfy.sh until the operator runs `ntfy-init.sh` and sets the own
host, `SIDEKICK_PUSH_AUTH_HOST` and the token (see `deploy/selfhost/selfhost.env.example`); the public ntfy.sh
service stays a fallback. Why: as few external dependencies as possible, no free-tier quota, and a push
server that never sees content.

### D-081 - Offline license keys

Status: Amended; the clause wording is superseded by D-083, the mechanism stands.
A license key is a signed string (Ed25519) that the instance checks offline against the licensor's public
key, taken from `SIDEKICK_LICENSE_PUBLIC_KEY` or else the default in `backend/src/sidekick/license/public_key.py`.
No network is involved. With no usable public key every key counts as unlicensed, and an unusable value never
stops the start. The binding terms are in `LICENSE.md`; the early draft of the clause is history.

### D-082 - Remove the old web shell

Status: Accepted (2026-11-10).
The previous React single-page application (Deck, Workspace, old chat, assistant, settings, session login)
and the REST routes only it used are removed. What remains is the MCP Apps rooms, the Android app, the
backend with MCP and companion, the work package and self-hosting. Features that existed only in the web
shell are given up. Database tables and migrations are not changed by this
decision. Why: a slimmer repository before publication.

### D-083 - License: Roadlake Sidekick Source Available License

Status: Accepted (2026-11-10).
Sidekick is source available, not open source. The license is titled "Roadlake Sidekick Source Available
License". It uses the Sustainable Use License 1.0 verbatim plus a short set of additional terms: a license key
and an unpaid notice, distribution only with the notice kept (also private and internal repositories), keys
issued only by the licensor, keys carrying an expiry date, and Swedish law. The licensor is Carl O Mattsson.
`LICENSE.md` is the binding text; legal review is still recommended.

### D-084 - Remove the old chat engine

Status: Accepted (2026-11-10); continues D-082.
The old chat engine and everything only it used are removed: the chat service and turn runner, the proposal
and confirmation flow, assistant evaluation, model providers, the Hindsight chat adapter, the daily
operations review, and the journal AI, conversation analysis, live voice and chat-stream settings. The rule:
keep what an MCP tool, an MCP app or the Android app reaches through a call chain. The memory tools and
worker, the activity log and automation policy read by the Control app, process runs in the automation
worker, the push sender and the voice entry remain. Data is not deleted: tables, models and migrations are
untouched, and retired setting names are tolerated and ignored at startup.

Correction (2026-11-11): the sentence "Data is not deleted: tables, models and migrations are untouched" described the
state when this decision was taken. The 0.1.0 baseline (`migrations/100_baseline_0_1_0.py`) does not create the retired
tables, and an in-place upgrade of an older installation is not supported, so data of the removed features is not
carried over; see `docs/explanation/schema-baseline.md`.

Correction (2026-11-11): the clause "retired setting names are tolerated and ignored at startup" no longer holds.
Legacy compatibility was removed: `Settings` forbids every undeclared `SIDEKICK_*` name, including the names of
removed features, and `SIDEKICK_MCP_OAUTH_SCOPES` no longer drops `chat:read` and `chat:write`.

### D-088 - Experimental voice entrance and direct probe removed

Status: Accepted (2026-11-11); supersedes [D-085](archive.md#d-085---home-assistant-voice-entrance-on-loopback) and [D-086](archive.md#d-086---direct-channel-measurement-probe).
The Home Assistant voice entrance (`/voice-mcp`, its own process), the direct-channel measurement probe
(`/app-mcp/ping`, the app-only `direct_probe_ping` tool and the probe build of the app) and the sandbox
instance label are removed, with their tests, deployment recipe and documentation. Why: the Android companion
app is only for checking small things, and speech is handled by Claude and other MCP clients, so Sidekick keeps
no voice entrance of its own. The settings `SIDEKICK_VOICE_MCP_OWNER_ID`, `SIDEKICK_APP_DIRECT` and
`SIDEKICK_MCP_INSTANCE_LABEL` are retired names: an existing env file that still sets them starts as before and
the values are ignored. (Correction 2026-11-11: no longer; see the correction under D-084.)

### D-089 - Persistence is PostgreSQL behind least-privilege roles

Status: Accepted (2026-11-11); recorded as [ADR-006](adr/ADR-006-persistence-and-idempotent-writes.md).
Persistence is PostgreSQL behind three roles (owner, migrator, app). The runtime cannot change the schema or
rewrite the audit and event history, migrations are expand-only unless marked as contract steps, and every
write is a versioned, idempotent command whose replay record holds identifiers only. It documents the
delivered design and changes no behaviour.

### D-090 - Credentials are keyed digests; scopes are enforced in the use cases

Status: Accepted (2026-11-11); recorded as [ADR-007](adr/ADR-007-authentication-credentials-and-scopes.md).
Personal tokens, GitHub OAuth sessions and companion device credentials are stored as keyed digests with a
purpose column, resolve to one verified actor, and carry scopes from a closed vocabulary that the use cases
check and that verification clips. It documents the delivered design and changes no behaviour.

### D-091 - Memory is derived and optional

Status: Accepted (2026-11-11); recorded as [ADR-008](adr/ADR-008-derived-memory-with-hindsight.md).
PostgreSQL stays authoritative, Hindsight sits behind the `MemoryProvider` port, one reconcile pass is the
only writer, and recall releases a fact only after Postgres confirms its source, scope and settings. It
documents the delivered design and changes no behaviour.

### D-092 - One curated public MCP surface

Status: Accepted (2026-11-11); recorded as [ADR-009](adr/ADR-009-one-curated-public-mcp-surface.md).
Sidekick has one public, curated MCP surface (`/mcp`, the list in `contracts/mcp-tools.generated.json`), shown as
MCP apps inside Claude. It has no built-in chat engine, agent server or standalone web client, and the Android app
uses the separate `/companion/v1` API over the same use cases. It documents the delivered design (see D-064, D-082
and D-084) and changes no behaviour; ADR-001 and ADR-002 are marked Superseded in part by it.

### D-093 - One error tree rooted at SidekickError

Status: Accepted (2026-11-12); recorded as [ADR-010](adr/ADR-010-one-error-tree.md).
All exception classes in `backend/src/sidekick` derive from `SidekickError`, which carries a closed `code`. The API,
MCP and companion boundaries translate errors by class and code, and a policy test fails when a class outside the tree
is added. It documents the delivered design and changes no behaviour.
