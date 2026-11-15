# Changelog

All notable changes to Roadlake Sidekick are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

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
  create a task, one revocable token per integration, managed with `sidekick-webhooks`.
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
