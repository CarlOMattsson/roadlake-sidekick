<p align="center"><img src="assets/brand/sidekick-favicon.svg" width="112" height="112" alt="Roadlake Sidekick app icon: a road curving around a lake."></p>

# Roadlake Sidekick

<p align="center">
<!-- release badges are added with the first release (v0.1.0) -->
<a href="LICENSE.md"><img src="https://img.shields.io/badge/license-Source%20Available-blue" alt="License: Source Available"></a>
<a href="https://roadlake.com"><img src="https://img.shields.io/badge/web-roadlake.com-informational" alt="Website: roadlake.com"></a>
</p>

Roadlake Sidekick is a personal assistant you run on your own server: you ask Claude about your tasks, journal, contacts and shopping, and your data stays in your own database.

[Svenska](README.sv.md) · [Documentation](docs/README.md) · [Quickstart](QUICKSTART.md) · [License](LICENSE.md) · [Contributing](CONTRIBUTING.md) · [Security](SECURITY.md) · [Decisions](docs/decisions/log.md)

> **Status: first version, not yet released.** Version 0.1.0 has no tag yet, so for now you build the container image and
> the APK from this repository. From the first release on, every release carries a signed image and a signed APK. It is in daily use with Claude, with the Android app on a real phone and on Linux; macOS
> has not been tried yet. Details: [docs/maintainers/release.md](docs/maintainers/release.md).

Roadlake Sidekick is a self-hosted, MCP-first operating system for one person for work and tasks, journal, shopping and
contacts. You talk to it through Claude; interactive MCP Apps rooms open inside the conversation when you
want to work with the result. A companion Android app uses the same records on your server.

Sidekick is **AI-first**: many changes are made by asking Claude rather than through a form for every field.
The rooms give direct controls for the supported workflows, and everything is stored as durable records in
your own PostgreSQL database.

## What you get

| Area | Capabilities |
| --- | --- |
| **Work** | Agenda, status board, domains, processes, projects, tasks and steps; dates, priorities, tags, estimates, waiting context and recurring work. |
| **Journal** | Several entries per day, manual writing and editing, entries and summaries written by Claude, linked context. |
| **Contacts** | People, organisations, roles, contact channels and relationship notes, linked to tasks, projects and journal entries. |
| **Shopping** | Lists, quantities, store groups, purchase ticks and undo. |
| **Control** | Trash and restore, recent changes, and controls for Sidekick's memory. Permanent deletion is not a public tool. |
| **Memory** | Optional Hindsight memory derived from your records, with per-source switches, pause and per-record exclusion. |
| **Android** | Pairing, a Today widget, Work, Journal and Shopping rooms, reminders over UnifiedPush (ntfy). |

The MCP apps' labels are Swedish by default (Arbete = Work, Dagbok = Journal, Inköp = Shopping, Kontroll = Control).
Set `SIDEKICK_MCP_APP_LOCALE=en` on the server for English. The Android app has its own language setting; see
[Languages](docs/reference/languages.md#the-android-app).

## Talk your day through with Claude

The most effective way to use Sidekick is a conversation with Claude in voice mode while you walk, cycle or drive. Don't dictate commands: let Claude ask about your day and talk freely about whatever is on your mind. Ten minutes of conversation usually turns into a good number of tasks, journal entries and links, and clears your head of the things that keep going round in it.

- Start with something like: "Ask me how my day has been, and help me get on top of everything I need to do."
- Claude asks follow-up questions: who is involved, when it has to happen, what belongs together. Then it creates the tasks, journal entries and contacts in Sidekick and links them.
- With other connectors in Claude, it can also go through Slack, email and your calendar to add tasks you missed and book meetings.
- Only talk when it is safe, for example hands-free in the car.

## What Claude can do

Claude works through a curated set of MCP tools, so you ask in plain language and it picks the tool. The core tools per room (all of them are in the [MCP tool reference](docs/reference/mcp/index.md)):

- **Overview:** `get_today_brief` for what matters today, `search` across your records, `list_recent_changes` for what changed.
- **Work:** `get_work_agenda` and `get_work_board`, `list_tasks`, `create_task` and `update_task`, plus steps, projects and processes.
- **Journal:** `write_journal_entry`, `get_journal_day` and `list_journal_entries`, and `set_daily_journal_summary` for a day's summary.
- **Contacts:** `list_contacts`, `create_contact` and `get_contact_context`, with links to tasks and projects.
- **Shopping:** `get_shopping_list`, `add_shopping_items` and `set_shopping_items_purchased`.
- **Control and memory:** `move_to_trash` and `restore_from_trash`, and `recall_memory` when the optional memory is on.

## What it looks like

The rooms in Swedish, the default language, with fictitious sample data in a simulated host:

<table>
  <tr>
    <td align="center" valign="top"><img src="docs/images/rooms/work-status-board-dark.png" width="200" alt="Work room, status board in dark mode, with a To do group of fictitious tasks."><br><strong>Work</strong><br>Status board, dark mode</td>
    <td align="center" valign="top"><img src="docs/images/rooms/journal-day.png" width="200" alt="Journal room showing one day with week navigation, a daily summary and an entry."><br><strong>Journal</strong><br>A day with its summary</td>
    <td align="center" valign="top"><img src="docs/images/rooms/contact.png" width="200" alt="Contacts room showing a fictitious supplier with role, organisation and notes."><br><strong>Contacts</strong><br>A person in context</td>
    <td align="center" valign="top"><img src="docs/images/rooms/shopping-list.png" width="200" alt="Shopping room showing a list grouped by store with purchase progress and quantities."><br><strong>Shopping</strong><br>A list grouped by store</td>
  </tr>
</table>

## How it fits together

Claude and the Android app talk to one Sidekick server. The server applies one set of rules to every request and keeps your records in PostgreSQL, with optional memory and push reminders around it. [How the parts fit together](docs/explanation/overview.md) explains each part, with a diagram.

## Run it

There are two ways. Pick by where Claude will run.

**1. Locally on your computer (simplest).** Sidekick and its database run in Docker on your own machine, and you use it from Claude Desktop through a local MCP server. Everything Sidekick stores and runs stays on your computer.

- You need no public address, domain, TLS certificate or GitHub account, and this route has no phone access.
- You need Linux or macOS with Docker (untested on macOS, see [the macOS notes](docs/operate/work-laptop/macos.md)) and Claude Desktop.
- Only for the optional private Hindsight memory you also need the address of an OpenAI-compatible model server. The setup asks first whether to turn the memory on; the default is no, and then no model server is needed.
- You choose the rooms. What you do in Claude Desktop is still shared with Claude.
- Guide: [Sidekick on a work laptop](docs/start/work-laptop.md) (Swedish: [Sidekick på jobbdatorn](docs/start/work-laptop.sv.md)), started with `bash tools/work.sh setup`.

**2. Your own server, reachable from Claude on the web and phone.** You run Sidekick on a Linux x86_64 machine with Docker Compose, a VPS or an always-on home computer. This route needs a Claude plan that supports custom connectors, a public HTTPS address for the server (a domain, or a tunnel to it) and a GitHub account (used to sign in). It is also the route for the Android app. Guide: [First start on a server](docs/start/self-hosted-server.md#first-start).

Sidekick sends no telemetry or analytics; it only contacts the services you configure (GitHub sign-in, push, and the model provider for optional Hindsight memory).

### More on the self-hosted server

- **Self-hosted server:** [deploy/selfhost/](deploy/selfhost/) starts with
  `git clone https://github.com/CarlOMattsson/roadlake-sidekick.git`, then copies the `*.example` files, generates your
  secrets, creates the owner and registers the GitHub sign-in before the first `up`. Profiles: `vps` (Caddy terminates TLS
  on your domain) or none (home: bring your own public HTTPS tunnel to `127.0.0.1:8000`).

  Claude's remote connector needs a **public HTTPS origin**; LAN-only access is not enough. Optional profiles:
  `memory` (private Hindsight), `backup` (encrypted owner exports) and `push` (reminders through a hardened
  own ntfy). `update.sh` defaults to a dry run and verifies a digest-pinned, signed image before applying.
  Backups cover owner product data, not a full server image; keep an off-server copy. To connect Claude to
  the running server, see [Connect Claude](docs/operate/connect-claude.md); to pair the Android app, see
  [Android app](docs/operate/pair-android.md).
- **Developers:** Sidekick can also run as a local stdio MCP server for Claude Desktop from a source checkout; see step 4 of [Run Sidekick locally as a developer](docs/start/first-contribution.md).
- **Android app:** from the first release on, install the signed APK attached to the GitHub release, or build the app
  from this repository (JDK 21, Android SDK 36, Node.js 22), and pair it with your server; see [Build, install and pair Android](docs/operate/pair-android.md).

## Develop

You need Python 3.13 with `uv`, Node.js 22 / npm 10 and Docker (for PostgreSQL).
Full steps in [Run Sidekick locally as a developer](docs/start/first-contribution.md):

```bash
git clone https://github.com/CarlOMattsson/roadlake-sidekick.git
cd roadlake-sidekick
[ -f .env ] || cp .env.example .env
uv sync --project backend --all-groups
npm --prefix frontend ci
docker compose -f deploy/compose.dev.yaml up -d db
uv run --project backend yoyo apply --batch \
  --database postgresql+psycopg://sidekick_migrator:sidekick_migrator@127.0.0.1:55440/sidekick migrations
uv run --project backend uvicorn sidekick.api.app:create_app --factory --reload --no-access-log   # from the repository root
npm --prefix frontend run build:mcp-app   # rebuilds the checked-in MCP App resource
```

Sidekick is a modular Python monolith. The FastMCP tools and the companion routes for the Android app call the
same application use cases; PostgreSQL owns records, identity and durable events. See [AGENTS.md](AGENTS.md) for the
conventions that apply to contributors and coding agents, and [CONTRIBUTING.md](CONTRIBUTING.md) for how to
report a bug or suggestion (pull requests are welcome, with a CLA, but handled in a limited way); the checks are in the [development guide](docs/contribute/development.md). The decisions that the code refers to as `D-0xx` are in
[docs/decisions/log.md](docs/decisions/log.md).

## Security

Identity is established by the server, with owner filtering and explicit scopes on every request. Logs and
traces carry no user content or credentials. Claude can read the content that the connector's scopes permit,
including journal text; self-hosting does not keep that content away from Claude or a memory/model provider
you configure. Never commit populated `.env` files or credentials. Report vulnerabilities privately, as
described in [SECURITY.md](SECURITY.md).

## License

Sidekick is **source available**, not open source. It is licensed under the **Roadlake Sidekick Source Available License**, which is the
Sustainable Use License 1.0 with the Roadlake Sidekick Additional Terms; see [LICENSE.md](LICENSE.md) for the binding text. In short, you may use and
modify it for your own internal business purposes or for non-commercial and private use, and distribute it
free of charge for non-commercial purposes. You may pay a consultant or agency to install, adapt and
maintain it on your own installation, but nobody may sell it or offer it as a hosted service. A license key is verified offline; it is never needed to
exercise a right under the license, but without a valid key the software shows an unpaid notice, and a
valid key removes that notice; the notice may not be removed or hidden, and the key check may not be
circumvented. The summary is not the license: the text in `LICENSE.md` governs.
For the license in plain words, how to enter a key and the planned prices, see [License, license key and price](docs/explanation/licensing.md).
Third-party components keep their own licenses; they are listed in [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).

### License keys

A license key is optional and checked offline; without one the software shows an unpaid notice, and nothing else changes. Operators store a key with `python -m sidekick.license.cli set` and check it with `python -m sidekick.license.cli show`. How keys are verified, which public key the instance uses and how to check the setup are in [Enter a license key](docs/operate/license-key.md#how-the-key-is-checked); the plain-words summary and prices are in [License, license key and price](docs/explanation/licensing.md).
