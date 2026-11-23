# Move data between installations

[Svenska](move-data.sv.md)

<!-- description: Move your records from one 0.1.0 installation to another, for example to a new server. Data from installations before 0.1.0 cannot be imported. -->

Move your records from one 0.1.0 installation to another, for example to a new server. Data from installations before 0.1.0 cannot be imported.

## Moving your data between 0.1.0 installations

Use this to move to a new server or a fresh database. The source must be a 0.1.0 installation that has an owner backup
(`sidekick-backup create`, or the backup profile) or can make an owner export. The importer reads only the current
format (format 11) and the seven formats before it (format 10, written before repetition existed, format 9, written before photos were exported, format 8, written before automations existed, format 7, written before AI steps existed, format 6, written before Tasks remembered when they were last reviewed, format 5, written before the tags of Contacts and Journal entries, and format 4, written at the baseline head). There is no supported way to import data from an
installation before 0.1.0: backups, exports, snapshots and SQL dumps from before 0.1.0 are not read, and
`sidekick-backup import` cannot import them. Keep them as an archive.

1. **Make a final backup in the old 0.1.0 installation** and keep the key file private.
2. **Start the new installation** from an empty database ([self-hosted setup](../start/self-hosted-server.md)). The
   migrator creates the baseline.
3. **Create the owner** in the new installation: `sidekick-admin create-user --login LOGIN --display-name NAME`. Use the same GitHub id as before if you
   sign in through GitHub.
4. **Import.** Give the key the backup was encrypted with, as `SIDEKICK_BACKUP_ENCRYPTION_KEY` in the environment or with `--key-file FILE` (mode 600). A key generated for the new installation cannot decrypt the old backup. First the plan, which writes nothing, then the same plan applied with its checksum (`deploy/selfhost/restore.sh --backup FILE --target-owner UUID [--source-owner UUID]`, then add `--apply`). A plain `.json` owner export needs no key. Counts per collection are checked after the write.
   Without the wrapper, on the dev stack: `uv run --project backend sidekick-backup import FILE --target-owner UUID` prints the plan and its `plan_checksum`; then run the same command with `--apply --plan-checksum SHA` and that checksum.
5. **Check the result**: open the Work and Journal rooms in Claude and compare the counts the importer printed.

What is not in an owner backup and therefore has to be made again: personal access tokens, OAuth registrations and
tokens, paired phones, push registrations, the license row, operational locks and derived memory metadata. Record
ids are mapped to new ids, so ids copied into old conversations no longer point at anything. The memory is rebuilt by
the memory worker from the imported records.

AI steps come with the backup, but an approved AI plan does not: approve it again on the new installation. A run that
was queued or running is restored as cancelled.

Repetition comes with the backup (the settings, the cards with their schedules, and every answer with its key). Each
card follows its contact to the new ids and keeps its schedule. Add `--refold` to `sidekick-owner-export restore` to fold
every restored card's answers again and see how many cards have a stored schedule that the answers do not give (a cut or
changed file); the rows are kept either way, and the command exits with 3 when any differ.

Automations come with the backup (the definitions, their runs, the facts they read, the suggestions and the checks of
them), but an approval does not: approve each automation again on the new installation, so that two installations never
run one definition on a single approval. A run that was queued, running or checking is restored as cancelled, with no
lease and no reserved spending. A suggestion that names a project or a created record follows it to the new ids. A
suggestion that was still being checked is shown as pending without a check. A suggestion you dismissed can be proposed
again after the move, because the memory of what was proposed is tied to the installation.

## Size limit of the encrypted database snapshots

The encrypted database snapshots that `update.sh` takes (and the work package's backups, which use the same
`deploy/selfhost/snapshot_crypto.py`) are encrypted with Fernet, which is not a streaming format: the whole dump is held
in memory. The ceiling is **512 MiB of plaintext** (the dump as pg_dump writes it, before encryption). A larger dump is
refused with `backup encrypt refused: input is over the 512 MiB ceiling`, nothing is written, and the update or backup
stops before it changes anything. Decryption has the matching ceiling for the encrypted file. If your dump is near the
limit, make room on the database first (prune old data) or take your backup with a tool that streams, outside Sidekick.
