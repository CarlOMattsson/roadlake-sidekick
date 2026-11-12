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
| [Frequently asked questions](faq.md) | Short answers about cost, privacy, keys and connections. |

## Operate a server

| Document | What it covers |
| --- | --- |
| [Operate](operate/README.md) | A map of what you do when you run a Sidekick server. |
| [Connect Claude](operate/connect-claude.md) | Add your server as a custom connector and sign in with GitHub. |
| [Build, install and pair Android](operate/pair-android.md) | Install the signed APK from a release or build the app from source, and connect the phone with a one-time code. |
| [Update](operate/update.md) | Update from source or to a signed image. |
| [Backup and restore](operate/backup-and-restore.md) | Encrypted backups and reading them back. |
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
