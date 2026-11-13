# Move data between installations

[Svenska](move-data.sv.md)

<!-- description: Move your records from one 0.1.0 installation to another, for example to a new server. Data from installations before 0.1.0 cannot be imported. -->

Move your records from one 0.1.0 installation to another, for example to a new server. Data from installations before 0.1.0 cannot be imported.

## Moving your data between 0.1.0 installations

Use this to move to a new server or a fresh database. The source must be a 0.1.0 installation that has an owner backup
(`sidekick-backup create`, or the backup profile) or can make an owner export. The importer reads only the current
format (format 6), which only 0.1.0 writes, and the two formats before it (format 5, written before the tags of Contacts and Journal entries, and format 4, written at the baseline head). There is no supported way to import data from an
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

## Size limit of the encrypted database snapshots

The encrypted database snapshots that `update.sh` takes (and the work package's backups, which use the same
`deploy/selfhost/snapshot_crypto.py`) are encrypted with Fernet, which is not a streaming format: the whole dump is held
in memory. The ceiling is **512 MiB of plaintext** (the dump as pg_dump writes it, before encryption). A larger dump is
refused with `backup encrypt refused: input is over the 512 MiB ceiling`, nothing is written, and the update or backup
stops before it changes anything. Decryption has the matching ceiling for the encrypted file. If your dump is near the
limit, make room on the database first (prune old data) or take your backup with a tool that streams, outside Sidekick.
