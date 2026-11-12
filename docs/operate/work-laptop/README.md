# Operating the work package

[Svenska](README.sv.md)

<!-- description: The work package runs locally against Claude Desktop and has a closed network, so it has its own operating guides. -->

The work package runs locally against Claude Desktop and has a closed network, so it has its own operating guides.

- [How the network is closed](network.md): the containers have no route out, and how to allow more addresses.
- [Start at login](start-at-login.md): let Sidekick start when you log in.
- [Backup and update](backup-and-update.md): encrypted backups, updating and going back.
- [macOS](macos.md): what differs from Linux.
- [The model server](model-server.md): what the server has to support and how to configure it.
- [Stop and uninstall](uninstall.md): stop Sidekick or remove everything.

## Rooms

Only the rooms you need can be enabled. The guide asks which rooms you want and proposes every room except shopping:
`SIDEKICK_ENABLED_ROOMS=work,journal,contacts,control` in `deploy/work/work.env`. Press Enter to take the proposal, or answer `-` to switch every room on. The list must include `work` (Sidekick does not start without
it); the other rooms are `journal`, `shopping`, `contacts` and `control`. The value goes into the api container's environment, so the
HTTP surface and the stdio process Claude Desktop starts (it runs in the same container) show the same rooms. Change
the line and run `bash tools/work.sh start` again.

| Room value | What it offers |
| --- | --- |
| `work` | Work: agenda, status board, domains, routines/processes, projects, tasks and steps. Required. |
| `journal` | Journal: dated entries, sources and draft review. |
| `shopping` | Shopping: lists, items and purchase check-offs. |
| `contacts` | Contacts: people, contact details and links to work records. |
| `control` | Control: trash and restore, recent changes and derived-memory controls. |

For example, `SIDEKICK_ENABLED_ROOMS=work,contacts,control` enables three rooms. Disabling a room hides its
navigation and MCP tools, and excludes its records from cross-room reads such as search; it keeps existing data.
An empty or removed setting enables all rooms. The `-` shortcut belongs to `setup`, not to the setting value.

## Phone

A local MCP server cannot be reached from Claude on a phone, because the phone app needs a connector with a public
address. There is no mobile route in this version.
