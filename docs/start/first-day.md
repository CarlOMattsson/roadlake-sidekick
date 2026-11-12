# Your first day with Sidekick

[Svenska](first-day.sv.md)

<!-- description: An eight-step tour of all four rooms, from today's overview to the trash, once Claude is connected to your server. -->

Once the connector is connected you can try all four rooms in a single conversation. A connector is the link between Claude and your server. Follow the steps in order, since they build on each other.

The questions below are suggestions. Use your own words. Claude picks tools from what you ask for, and the answers will not look the same every time.

:::note[Before you start: give Claude the right permissions]
A scope is a permission that the server checks on every call. The example configuration gives Claude read access only, to projects, tasks, contacts and shopping. To follow the whole guide the session also needs `tasks:write`, `contacts:write`, `shopping:write`, `journal:read` and `journal:write`. [Read how to change what the session may do](../operate/connect-claude.md).
:::

## 1. Ask how today looks

You could ask, for example:

> How does my day look?

Claude fetches today's overview from Sidekick: what is due today and what is overdue. A new installation holds nothing yet, so the answer will be short.

## 2. Create a task

You could write, for example:

> Add a task: call the dentist on Friday.

Claude creates the task in the Work room (Arbete). Then ask Claude to show the agenda. The room can then open in the conversation, as a card or in full screen.

## 3. Check off and undo in the room

Tap the ring in front of the task to mark it done. The row stays for a short while with an "Ångra" (Undo) button. Tap it to bring the task back.

This happens in the room. You do not need to wait for a new answer from Claude.

## 4. Write in the journal

You could write, for example:

> Write in my journal that I finally booked the dentist.

Claude saves an entry on today's date in the Journal room (Dagbok). You can also write by hand: open Journal and tap + next to the date.

## 5. Add a contact

You could write, for example:

> Add my dentist Anna as a contact and link her to the task.

Claude creates the contact in the Contacts room (Kontakter) and links it to the task. Open the contact to see the link under Tasks.

## 6. Make a shopping list

You could write, for example:

> Make a shopping list for the weekend with milk, coffee and two litres of yoghurt.

Claude creates the list in the Shopping room (Inköp). In the room, tap the ring in front of an item when you have bought it.

## 7. See what changed

You could ask, for example:

> What have I changed today?

You can also open Control (Kontroll), the last item in the ⋯ menu of every room. The History tab lists the changes, newest first.

## 8. Move something to the trash

You could write, for example:

> Move the dentist task to the trash.

The tool tells Claude to ask you first and wait for a yes. That is an instruction to Claude, not a check in the server. Nothing is deleted for good: open Control, choose the Deleted tab and tap "Återställ" (Restore) to bring the task back.

## What Claude can read

Claude reads what the connector's scopes allow. If you added `journal:read`, that includes journal text. What Claude reads leaves your server and is shared with Claude.

[Read who sees what](../explanation/security-and-privacy.md)

## Change the language of the rooms

The rooms' labels are Swedish by default. Set `SIDEKICK_MCP_APP_LOCALE=en` on the server for English. [Read more about languages](../reference/languages.md).

## Next steps

- [Read how the conversation and the rooms fit together](../guide/README.md)
- [Turn on memory](../operate/memory.md)
- [Build and pair the Android app](../operate/pair-android.md)
