# Control and memory

[Svenska](control-and-memory.sv.md)

<!-- description: Control gathers the trash, the history and Sidekick's memory. How to restore things, see what changed and decide what memory may hold. -->

Control is where you see what happened and decide over memory. Its heading is "Minne och kontroll" (Memory and control). You open it with "Minne och kontroll", the last item in the ⋯ menu of every room, and it opens on Sidekick's memory tab. It has three tabs: Deleted (Borttaget), History (Historik) and Sidekick's memory (Sidekicks minne).

## Restore something from the trash

1. Open Control and choose the Deleted tab.
2. Tap "Återställ" (Restore) on the row.

Deleting something, in a room or through Claude, only moves it to the trash. It stays there until whoever runs the server empties it.

## See what changed

The History tab lists the changes and what Claude has done, newest first. The rows have "Ångra" (Undo) or "Återställ" (Restore) where that is possible.

## How memory works

Memory is optional and off from the start. Whoever runs the server turns it on. [Read how to turn on memory](../operate/memory.md).

Memory is derived from your records. Your records in PostgreSQL are the truth, and memory can be rebuilt from them. When Claude asks memory, Sidekick checks the answer against what is in the database right now, so that something you removed does not come back.

Memory is built by the Hindsight service, which calls a language model at the provider you configured yourself. Text from the sources you have switched on is sent there. Contacts' email, phone and address are never sent.

## Pause memory

Open the Sidekick's memory tab and tap "Pausa minnet" (Pause memory). Tap "Återuppta minnet" (Resume memory) to start it again.

## Switch off a source

Under Källor (Sources) there is one switch per source: journal, contacts, projects and tasks. When you switch a source off, what memory derived from it is removed.

## See what memory holds

Under each source that is on, tap "Visa vad Sidekick minns" (Show what Sidekick remembers) for a sample of what memory holds. The search field asks the whole memory.

## Keep a single record out of memory

Tap "Glöm anteckningen" (Forget the entry; for a contact, project or task the button names that record) on a fact, and confirm with "Ja, glöm …" (Yes, forget …). Everything memory holds from that whole record, not just that fact, is removed, and the record itself is unchanged. It can take a few minutes before it is gone from search. You can also ask Claude, for example: "Keep this journal entry out of memory." The record stays in the room but is not used by memory. You can ask Claude to let it back in.

## Enter a license key

The license row is at the bottom of Control. Without a key it says "Gratisversion" (Free version). Until license keys go on sale, the row says that they will soon be available to buy in place of a buy button. Choose "Ange licensnyckel" (Enter license key), paste the key into the field labelled "Licensnyckel" (License key), which shows the shape of a key as a hint, and choose "Spara" (Save). [Read more about entering a license key](../operate/license-key.md).

## What you cannot do from here

Permanent deletion is not a public tool. Neither Claude nor the rooms can delete anything for good. Whoever runs the server empties the trash with a command. [Read how to empty the trash](../operate/empty-trash.md).

## Scopes Control needs

A scope is a permission that the server checks on every call. Control and memory have no scopes of their own. They follow the areas you have given access to.

| To | Scopes |
| --- | --- |
| See the trash, the history and memory status | the read scope of the area, for example `tasks:read` |
| Move to the trash and restore | the write scope of the area, for example `tasks:write` |
| Pause memory, switch off a source, exclude a record | the write scope of the area, for example `journal:write` |
