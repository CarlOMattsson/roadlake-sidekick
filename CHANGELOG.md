# Changelog

All notable changes to Roadlake Sidekick are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.2.1] - 2026-11-19

### Added

- Repeating tasks on chosen weekdays, every other week, or the last weekday of the month (a weekend falls back to the
  Friday before); the rule is shown in plain words on the task.
- A calendar week view (Monday to Sunday) in the full-screen journal, beside the day view, which stays the default.
- In the full-screen shopping list and store view: step an item's amount with + and −, and move an item to another list
  from its row, with undo.
- Contact and project names in inline cards open the record in the full view.
- Waiting-on for tasks; due times shown and settable, kept when the date changes or tasks are moved in bulk; follow-ups
  stand in the agenda on their day.
- Journal: an entry written by hand keeps your own words and says whose summary it is; an entry can be kept out of
  memory.
- `update_shopping_item` can move an item to another list.

### Changed

- A monthly repeat without a day now follows the task's due date. It counts from the month the task was due and skips
  occurrences that have already passed, instead of counting from the day it was completed.
- The status board reads tasks only, most overdue first, and its column totals come from the server.
- History rows name the right actor (you, not Claude, for changes made in the app), one row per action, with the
  record's name.
- After a conflicting change, the app reloads the fresh state quietly instead of showing an error.

### Fixed

- A row in an inline card opens that record, not the start view.
- Slack, e-mail and phone links on a contact open through the host instead of emptying the app.
- Contact search matches what a row shows, archived contacts can be opened, and creating a contact with an existing
  name warns you.
- The compact shopping card and add flow work one-handed on a phone.

## [0.2.0] - 2026-11-17

### Added

- AI-delegated task steps (#26): Claude plans the steps, you approve them, they run, and you review the result.
  Planning, approving, running and reviewing are all available as tools.
- Optional server runner for AI steps, off by default: a separate `ai-worker` in the `ai` Compose profile, with your
  Anthropic key in a file that only the worker reads, a monthly and a per-task spending cap, and attempts counted per
  cycle.
- Opt-in "AI this month" row in Control with the month's AI cost (`SIDEKICK_MCP_APP_SHOW_AI_USAGE`, off by default).
- Android app: tasks, projects and journal entries written without a network are kept and sent when the connection
  returns; queued journal entries are encrypted.
- Completing a task completes its open steps, and a repeating task starts its steps over for the next run.
- Board column headings show the server's real totals, and inline board and agenda cards have a refresh button.
- Compact `list_tasks` rows, and per-task project, domain and description in `create_tasks`.
- Contacts: an optional Slack profile link (`https://<workspace>.slack.com/team/<member id>`) shown under ways to
  reach a contact; it opens the person in Slack, one tap from a direct message.

### Changed

- Update tools (breaking for MCP clients, #29): `null` in `changes` now means "not sent". To empty a field, name it in
  the new `clear` list. Replies list the nulls that were ignored. The companion API is unchanged.

### Fixed

- Update tools accept a `changes` object that carries schema defaults, and a refused change names the failing path.
- Shopping: a null quantity in an item update is refused, as the schema has never allowed it.
- AI steps: accepting a result is bound to the approved plan, only the client that started a run may report it, the
  cost of erased runs still counts toward the spending caps, and a model call is capped at the time the worker has
  left when it is stopped.
- Work app: a Task marked done goes back only to the list it was opened from.
- Android app: an emptied journal queue is erased, edits are sent whole, and Back is registered before the first paint.
- `license_issue` treats only a real git repository as a git working tree.
- Transitive npm dependencies flagged by Dependabot are updated.

## [0.1.2] - 2026-11-15

### Added

- Android app: create and edit tasks and edit projects from the app, through new companion routes and the device
  capability `companion:work:write` (in `--preset app`; a device paired earlier needs a new pairing or a grant).
- Android app: move tasks, journal entries and shopping items to the trash with Undo, a trash screen in the settings,
  and permanent removal of trashed tasks behind its own capability `companion:work:erase` and an explicit confirmation.
- Android app: share text and links from other apps to Sidekick as a task or a journal entry.
- Guided review of many tasks for voice mode: `get_review_queue`, `review_tasks` and `restore_task`, and Ambitions,
  tasks you want to keep in view without reminders.
- Token-protected webhooks for home and phone automation (`/webhooks/v1/`, off by default): add a shopping item or
  create a task, one revocable token per integration, managed with `python -m sidekick.webhooks.cli`.
- Self-hosting: a `tailscale` Compose profile that publishes Sidekick through Tailscale Funnel from a home machine.

### Changed

- ADR-005: the Android app may now create, edit and delete, as a fallback when you cannot talk to Claude.

### Fixed

- Property-based fuzzing found and fixed four bugs: license keys signed as UTF-8, CSS escaping in the host style,
  prefixed routing and an invalid-day edge in the owner's noon.
- CodeQL findings fixed in code.

## [0.1.1] - 2026-11-15

The first public release.

Version 0.1.0 was never released. A release run stopped at the image scan after it had already pushed an unsigned `v0.1.0` image tag, and a version tag is never moved, so the first release is 0.1.1. The release workflow now scans, signs and attests the image by digest before it creates the version tag.

### Added

- MCP-first backend (FastAPI and FastMCP over one set of application use cases) with PostgreSQL storage and migrations.
- MCP Apps rooms for Claude: Work (agenda, status board, domains, processes, projects, tasks, steps), Journal,
  Contacts, Shopping and Control (trash and restore, recent changes, memory controls).
- Work records with dates, priorities, tags, estimates, waiting context and recurring work.
- Optional derived memory through Hindsight (off by default, so the local route needs no model server), with per-source switches, pause and per-record exclusion.
- Native Android companion app: pairing, Today widget, Work, Journal and Shopping rooms, and reminders over
  UnifiedPush (ntfy).
- Self-hosting with Docker Compose: a VPS profile with Caddy and TLS, a home profile behind your own HTTPS tunnel,
  optional memory, backup and push profiles, and a digest-pinned, signed-image updater. The self-hosting guide
  includes a local check, the authentication mode for personal access tokens and recovery from a failed first start.
- Work-laptop package that runs Sidekick and a private Hindsight in Docker and talks to Claude Desktop over a local
  MCP server. Its backups are encrypted with a key kept outside the backup directory, and `restore` needs the same
  key. An opt-in `work.sh claude-config` previews and merges only the Sidekick entry into Claude Desktop's
  configuration, with a timestamped backup.
- Public MCP authentication with scoped access, server-side authorisation, correlation ids on every request and
  sanitised structured logs.
- Owner data export as a server command, with encrypted owner backups (the self-hosted `backup` profile).
- License key handling for the source-available license, and Swedish and English user documentation.
- Release pipeline: one version for server, web bundle and Android app, a multi-architecture image signed with
  cosign, a signed APK, checksums, an image SBOM and release notes in one bundle; see [docs/maintainers/release.md](docs/maintainers/release.md).

### Security

- Permanent deletion is not offered as a public tool; deletion goes through trash and restore.
- Entering the license key (`set_license_key`) needs the `license:write` scope. A personal token or a
  `SIDEKICK_MCP_OAUTH_SCOPES` list must include it for the key to be entered in the app.

### Notes

- The database starts from a single schema baseline (see
  [The 0.1.0 schema baseline](docs/explanation/schema-baseline.md)).
- First-release status: in daily use with Claude, with the Android app on a real phone and on Linux. macOS has not been
  tried yet; see [docs/maintainers/release.md](docs/maintainers/release.md).
