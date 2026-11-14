# Changelog

All notable changes to Roadlake Sidekick are listed here. The format follows
[Keep a Changelog](https://keepachangelog.com/en/1.1.0/) and the project uses
[Semantic Versioning](https://semver.org/).

## [Unreleased]

## [0.1.0] - 2026-11-14

The first public release.

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
