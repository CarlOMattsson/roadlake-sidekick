# Roadlake Sidekick documentation

[Svenska](README.sv.md) · [Back to the README](../README.md)

This is the map of the documentation that ships with Roadlake Sidekick. Most user-facing guides exist in English and
Swedish; the reference, the architecture records, the decisions and the guide for coding agents are in English only.

New here? Start with one of these:

- [First start on a server](start/self-hosted-server.md): run Sidekick on a server you control.
- [Sidekick on a work laptop](start/work-laptop.md): the work package, used from Claude Desktop.
- [The conversation and the rooms](guide/README.md): how you work with Sidekick once it runs.

## Start

| Document | What it covers |
| --- | --- |
| [Choose your path](start/README.md) | Four ways to start: your own server, a work laptop, your first day, or development. |
| [First start on a server](start/self-hosted-server.md) | From a clean clone to a server that answers: requirements, secrets, build, owner and check. |
| [Sidekick on a work laptop](start/work-laptop.md) | The work package: Sidekick and a private memory in Docker on a laptop, used from Claude Desktop with outbound network access closed. |
| [Your first day with Sidekick](start/first-day.md) | One conversation that takes you through all four rooms. |
| [Run Sidekick locally as a developer](start/first-contribution.md) | Setup from a clone, the backend, a scoped token and a first look at the rooms. |

## User guide

| Document | What it covers |
| --- | --- |
| [The conversation and the rooms](guide/README.md) | How you work with Sidekick through Claude, and what each room is for. |
| [Work](guide/work.md) | The agenda, the status board and projects: create tasks, check them off, change dates and split them into steps. |
| [Journal](guide/journal.md) | One day at a time with a summary and entries: change day, write by hand and let Claude write for you. |
| [Contacts](guide/contacts.md) | People and organisations in context: search, add, edit and link contacts. |
| [Shopping](guide/shopping.md) | A list grouped by store: add items, tick off what you bought, undo and change quantities. |
| [Control and memory](guide/control-and-memory.md) | The trash, the history and Sidekick's memory. |
| [The Android app](guide/android-app.md) | What the app does and does not do, and how to get started. |
| [The Today widget and reminders](guide/today-widget.md) | Today's tasks on the home screen, and reminders through ntfy and UnifiedPush. |
| [Frequently asked questions](faq.md) | Short answers about cost, privacy, keys and connections. |

## Operate a server

| Document | What it covers |
| --- | --- |
| [Operate](operate/README.md) | A map of what you do when you run a Sidekick server. |
| [Connect Claude](operate/connect-claude.md) | Add your server as a custom connector and sign in with GitHub. |
| [Build, install and pair Android](operate/pair-android.md) | Install the signed APK from a release or build the app from source, and connect the phone with a one-time code. |
| [Update](operate/update.md) | Update from source or to a signed image. |
| [Backup and restore](operate/backup-and-restore.md) | Encrypted backups and reading them back. |
| [Turn on memory](operate/memory.md) | The `memory` profile: nothing is derived or sent until you turn it on. |
| [Run AI steps](operate/ai-steps.md) | Let your own Claude Code, or your server with your own Anthropic key, run the AI steps of an approved task. |
| [Push reminders through ntfy](operate/push-reminders.md) | Wake-ups with no content to the phone, which fetches what to show by itself. |
| [Enter a license key](operate/license-key.md) | In a room, in the Android app or from the command line. |
| [Empty the trash](operate/empty-trash.md) | Empty the trash for good with one command, and what is kept anyway. |
| [Move data between installations](operate/move-data.md) | Move your records from one 0.1.0 installation to another. |
| [Webhooks](operate/webhooks.md) | Let home or phone automation add a shopping item or a task through a token-protected endpoint. |
| [Resource limits and secrets](operate/limits-and-secrets.md) | The memory and process limits of each container, and the settings each one receives. |
| [Operating the work package](operate/work-laptop/README.md) | The network, start at login, backup and update, the model server and uninstalling. |

## Reference

| Document | What it covers |
| --- | --- |
| [MCP tool reference](reference/mcp/index.md) | Every MCP tool by area, with its scopes and parameters. Generated from the contract. |
| [Configuration reference](reference/configuration.md) | Every environment variable the backend reads. Generated from `Settings`. |
| [Command-line reference](reference/cli.md) | Every operator command with its arguments. Generated from the argument parsers. |
| [Scope reference](reference/scopes.md) | The MCP scopes and companion capabilities, and what uses each. |
| [Compose profiles and files](reference/selfhost-profiles.md) | Which services each profile starts, and what the files in the package are for. |
| [Languages in the rooms, the app and the server](reference/languages.md) | Where each language setting lives. |
| [MCP App design system](reference/design-system.md) | The visual and interaction rules for the rooms and inline cards. |

## Explanation

| Document | What it covers |
| --- | --- |
| [How the parts fit together](explanation/overview.md) | Claude and the Android app, one server with one set of rules, and PostgreSQL as the source of truth. |
| [Security and privacy](explanation/security-and-privacy.md) | Who sees what, in plain words. |
| [Threat model](explanation/threat-model.md) | What Sidekick protects, from whom, and which controls are in place. |
| [License, license key and price](explanation/licensing.md) | The license in plain words, what the optional key does, and the planned prices. |
| [The 0.1.0 schema baseline](explanation/schema-baseline.md) | What the single baseline migration is and why older installations are not upgraded in place. |
| [Backend layering](explanation/architecture/backend.md) | How the backend is split into layers, and which imports the tests forbid. |
| [MCP Apps as Sidekick's product frontend](explanation/architecture/mcp-apps.md) | How the rooms run inside Claude and on Android, and what a view may ask of the host. |

## For contributors and maintainers

### Decisions

| Document | What it covers |
| --- | --- |
| [Decisions and ADRs](decisions/README.md) | How to read the decision log and the architecture decision records, with the ADR index. |
| [Decision log](decisions/log.md) | The product and architecture decisions that code and documents cite as `D-0xx`. |

### Contribute and maintain

| Document | What it covers |
| --- | --- |
| [Development guide](contribute/development.md) | The checks a change must pass, the full test suite, generated files and code style. |
| [Maintaining Sidekick](maintainers/README.md) | Releasing a version, the release drill and the record of what has been verified. |

### Elsewhere in the repository

| Document | What it covers |
| --- | --- |
| [Contributing](../CONTRIBUTING.md) | How to report bugs and suggestions, and how pull requests and the CLA work. |
| [Developer quickstart](../QUICKSTART.md) | A short pointer to the developer pages. |
| [Security policy](../SECURITY.md) | How to report a vulnerability privately, and what is in scope. |
| [Changelog](../CHANGELOG.md) | Notable changes per release. |
| [License](../LICENSE.md) | The binding license text: Sustainable Use License 1.0 with the Roadlake Sidekick Additional Terms (source available, not open source). |
| [Guide for coding agents](../AGENTS.md) | The repository's conventions, boundaries and checks, written for human and AI contributors alike. |
| [Test database pool](../tools/test-db-pool.md) | Running database-backed tests in parallel without runs wiping each other's data. |
