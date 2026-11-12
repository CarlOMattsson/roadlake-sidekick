# Empty the trash

[Svenska](empty-trash.sv.md)

<!-- description: Deleting something only moves it to the trash. Here you empty it for good with one command, and see what is kept anyway. -->

Deleting something only moves it to the trash. Here you empty it for good with one command, and see what is kept anyway.

Deleting a record in the app or from Claude only moves it to the trash, where it can be restored. Nothing empties the
trash by itself: whoever runs the server does it with one command. Without `--yes` it only counts and deletes nothing:

```bash
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash --yes
docker compose --env-file selfhost.env run --rm -T api sidekick-admin empty-trash --yes --older-than 30
```

The first command prints how many records of each type are in the trash, for every user. The second removes them for
good; `--older-than DAYS` keeps what was trashed more recently. Records that are active or archived are never touched.
A record that still has descendants or links (for example a contact with a nickname) is kept and counted as kept;
remove the descendants and run the command again. A shopping item or a Journal entry cannot be removed for good at
all and is always counted as kept. The output holds only
counts and record types, never titles or text, and each removal is written to the audit log like a removal in the app.
Running it again is safe. Take a [backup](backup-and-restore.md) first if you might want the records back.

What is removed and what is not. The command deletes the record itself with the links and tags that hang on it, and, when
memory is on, queues the removal of its memory copy. It does not rewrite history. The activity feed and the change ledger are append-only:
they keep the title or name recorded at each change, and for Tasks also the description and field values, even after the
record is gone. The audit log keeps one line with the record type and id, no text. A Journal entry is never removed
for good, and neither is its source: sources are immutable and cannot be moved to the trash, and the entry stays
counted as kept (whether Journal entries may ever be erased is left open).
Backups made earlier keep everything until you delete them. When to empty the trash, and whether to purge history, is
your decision as the person running the server; Sidekick does not empty the trash or prune history by itself.
