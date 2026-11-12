# The conversation and the rooms

[Svenska](README.sv.md)

<!-- description: How Sidekick works. Claude does most things when you ask, and the rooms show the result and let you tap things directly. -->

Sidekick has no web interface of its own. You use it in a conversation with Claude, and the rooms open in the conversation when you want to see and change something yourself.

## Claude does most things

You ask Claude for what you want done, in plain words. Claude then calls tools on your server through MCP (Model Context Protocol), the protocol that lets Claude use tools outside the conversation. You do not need to know the tools' names.

Many changes are easiest to make by asking. Ask for a new task, a journal entry or ten items on a list, and Claude takes care of it. What Claude may read and change is decided by the scopes, meaning permissions, that you gave the connector.

## The rooms show and let you tap

There are four rooms, Work (Arbete), Journal (Dagbok), Contacts (Kontakter) and Shopping (Inköp), plus Control (Kontroll). A room is a view that Claude shows inside the conversation. There you check things off, change dates, write by hand and move between records.

At the top of every room is a strip with the four rooms, so you can switch rooms without asking Claude. Control is the last item in the ⋯ menu of every room.

## Cards in the conversation and full screen

An answer from Claude can contain a card: a compact box with a few rows. The card ends with a link that opens the whole room, for example "Öppna Status" (Open Status). In full screen you see the whole list and every control.

## Changes without a new answer from Claude

When you tap in a room, the change goes straight to the server. You do not need to wait for Claude to answer, and you do not need to type anything. When something has changed, the rooms that can show the change read their data again.

The server checks every change, whether it comes from Claude or from a room. The same rules apply to both.

## What is stored

What is stored is your records: tasks, entries, contacts and items. The text of the conversation is not stored in Sidekick automatically. If you want to keep something from the conversation, ask Claude to write it in the journal.

:::note[Preview]
The rooms are built and tested in a simulated host. They have not yet been tried in real Claude connections.
:::

## Language in the rooms

The rooms' labels are Swedish by default. Set `SIDEKICK_MCP_APP_LOCALE=en` on the server for English.

| Swedish | English |
| --- | --- |
| Arbete | Work |
| Dagbok | Journal |
| Kontakter | Contacts |
| Inköp | Shopping |
| Kontroll | Control |

The Android app has its own language setting. [Read more about language in the rooms, the app and the server](../reference/languages.md).

## The rooms one at a time

- [Work](work.md)
- [Journal](journal.md)
- [Contacts](contacts.md)
- [Shopping](shopping.md)
- [Control and memory](control-and-memory.md)
- [The Android app](android-app.md)
- [The Today widget and reminders](today-widget.md)
