# Backup and update

[Svenska](backup-and-update.sv.md)

<!-- description: Take encrypted backups of the database and the memory on your work laptop, update, and go back if an update fails. -->

Take encrypted backups of the database and the memory on your work laptop, update, and go back if an update fails.

With the memory on (`SIDEKICK_WORK_MEMORY=on` in `work.env`), `bash tools/work.sh backup` writes two files with the same timestamp to `deploy/work/backups/`: the database dump
(`sidekick-<time>.sql.enc`) and Hindsight's memory (`hindsight-<time>.tar.gz.enc`). With the memory off (`SIDEKICK_WORK_MEMORY=off`, the default, see [When the memory is off](#when-the-memory-is-off)) it writes only the first file. **Both are encrypted** (see
[The backup key](#the-backup-key)); no plain dump or archive is ever written to disk. Hindsight keeps its memory in an embedded
Postgres in the volume `hindsight_pg0`. So that the two copies match each other, the `api`, the `memory-worker` and the `automation-worker` are paused first
and started again when both copies are done (also if the backup fails or is interrupted). A copy of live database files is not consistent, so Hindsight is stopped for a
few seconds while the volume is archived (with `tar` from the pinned Hindsight image, offline, read-only mount) and
started again. The last seven of each kind are kept (`SIDEKICK_WORK_KEEP_BACKUPS` changes the number; it must be at least 1); the files are also readable by you only (600).
Before anything is paused, `backup` (and `update` and `restore --apply`, which take one) checks that `deploy/work/backups/` has
room for another set: the size of the newest set times `SIDEKICK_BACKUP_SPACE_MARGIN_PCT` (default 150, at least 100), and at least
`SIDEKICK_BACKUP_SPACE_FLOOR_MB` (default 64 MiB). With too little room, or a free size it cannot read, it refuses with a clear
message and changes nothing. Pruning runs only after the new set was read back, never removes that set or the newest finished
one, and touches only files named exactly `sidekick-<time>.sql.enc` and `hindsight-<time>.tar.gz.enc`. A backup counts only after it has
been **read back**: `backup` decrypts each file again, checks that the dump ends with pg_dump's end marker and that the
archive lists and is not empty, and only then reports it. A file that fails this check is removed and the command
fails (the writers and Hindsight are started again).

## When the memory is off

`SIDEKICK_WORK_MEMORY=off` is the default. Then Hindsight and the memory worker do not run and there is no Hindsight volume to back up:
`backup` prints "Memory is off; only the database is backed up." and writes only `sidekick-<time>.sql.enc`, and only the `api` and
the `automation-worker` are paused meanwhile. `restore` then needs just that file: it does not look for or touch a memory archive
and the plan marks the memory as off (a set that also holds a memory file is restored without it). If you switch the memory on later
(`bash tools/work.sh setup`, or `SIDEKICK_WORK_MEMORY=on` plus the model server settings in `work.env`, then `start`), it **starts empty**:
nothing is built up from the time it was off, and a database backup from that time holds no memory. A `work.env` from before the
setting existed has no such line and keeps the memory on.

## The backup key

The backups are encrypted with Fernet (authenticated encryption) by the same mechanism as the encrypted database
snapshots of a self-hosted installation (`deploy/selfhost/update.sh`), run in a one-off container of the Sidekick image
(`deploy/selfhost/snapshot_crypto.py`). The key is **a separate one**: not the `SIDEKICK_BACKUP_ENCRYPTION_KEY` of a
self-hosted installation, and not a secret of the running stack.

- **Where it is.** The first `backup` creates `deploy/work/secrets/backup.key` (mode 600, directory 700) and prints its
  path. The content is never printed or logged, and it reaches the container through the environment, not a command
  line. The key lives outside `deploy/work/backups/` on purpose; the command refuses a key file inside the backup
  directory. `SIDEKICK_WORK_BACKUP_KEY_FILE=/path/to/key` keeps it somewhere else instead, for example on a mounted key
  store.
- **Copy it off this machine, apart from the backups.** Right after the first backup, copy the key to a place that is not
  this laptop and not next to the backups: a password manager, or a USB stick kept separately. A backup in the same
  place as its key protects nothing, and a key that exists only on this laptop is lost with the laptop.
- **Losing the key means the backups are lost.** There is no recovery without the key: the files are authenticated
  ciphertext. `stop --purge` deletes `deploy/work/secrets/` and therefore the key together with the backups.
- **Fails closed.** `backup` and `restore` stop before anything is changed when the key file is missing or is not a valid
  key. If encrypted backups exist and the key is gone, `backup` does **not** create a new key (that would orphan the old
  backups): put the key file back from your copy. Only when no encrypted backup exists is a new key created.
- **Rotation.** Back up first, then move `deploy/work/secrets/backup.key` and the old files out of the way (keep them
  until the new backups are verified), run `backup` to get a new key and new files, and copy the new key off the machine.
  Old backups can only be restored with the old key: keep the old key and the old files together, or delete both.
  Rotate when the key may have been seen by someone else.
- **Backups from before encryption** (`sidekick-<time>.sql`, `hindsight-<time>.tar.gz`) are plain files, are not
  listed or restored by `restore`, and still hold all your data in clear: delete them once a verified encrypted backup
  exists.
- **Memory.** The encryption holds the whole file in memory while it works, the same limit as for the snapshots of a
  self-hosted installation; this is fine for a laptop's database and memory, not for multi-gigabyte data.

If `docker compose ps` cannot tell which writers are running, or one of them is still running after the stop, the
backup stops before copying anything. The commands that change the stack (`setup`, `init`, `start`, `stop`, `backup`,
`update` and `restore --apply`) share one lock (`deploy/work/.work.lock`, or the directory `deploy/work/.work.lock.d`
where `flock` is missing, as on macOS): while one of them runs, a second one is refused with "already running" and
changes nothing. `status` and the dry run of `restore` take no lock. A lock left by a command that no longer runs is
taken over automatically.

`bash tools/work.sh update` needs the repository to be **cloned with git** (`git clone`), not downloaded as a zip: the code is fetched with `git pull --ff-only`. The order is built so that the writers are stopped for as short a time as possible:

1. It keeps the image that runs now under the tag `roadlake-sidekick:previous`, fetches the code and checks the migrations it brought, as `deploy/selfhost/update.sh` does with the class label of its image: `tools/check-release-migration-class.py` compares them with the commit you were on, and a new migration that the old code cannot run against (`DROP`, `RENAME`, a column type change, `SET NOT NULL`, `REVOKE` or the marker `migration-class: contract`) makes `update` refuse, put the code back on your commit and change nothing else (nothing is stopped and no backup is taken). `bash tools/work.sh update --allow-breaking-migration` accepts such a migration; going back afterwards means restoring the backup it takes (below).
2. It pulls pinned images and builds Sidekick. None of that touches data, and the running stack keeps running meanwhile.
3. Only now does it stop the `api`, the `memory-worker` and the `automation-worker` and take the same `backup` with them stopped, so that no write falls between the backup and the migration; if either copy fails, nothing is migrated and the stopped services start again from the previous image.
4. The writers stay stopped while it runs the migration with the new image, starts the `api` alone and waits until it is ready (the database answers and the schema is at the revision of the new image, not just that the container is up); only then do the workers start, and it checks again.
5. Last it rewrites the Claude Desktop configuration and records the time and commit in `deploy/work/generated/build-info.json`.

The file is already created by `init` and `start`, shown by `status`, mounted read-only in the api container at `/etc/sidekick/build-info.json` and named by `SIDEKICK_BUILD_INFO_FILE`, so the interface's update reminder counts from day one (`SIDEKICK_UPDATE_REMINDER_DAYS`, 14 by default).

What happens on a failure depends on whether the migration has begun. **Before it** (the pull, the migration check or the build fails, the backup fails, or you interrupt), the code goes back to your commit, the previous image is put back under its name and, if the backup had stopped them, the services start again from it; the database was not touched. A failure before the stop changes nothing in the running stack. **From the migration on** the writers are left stopped and nothing is restored automatically, because the state of the database is uncertain; the message names the backup and the command to look at it (`bash tools/work.sh restore <time>`, first without `--apply`).

## Going back after a failed update

If the migration, the restart or the readiness check fails, `update` leaves the writers stopped and rolls nothing back. It prints the commit you were on (`<before>`)
and the one it moved to (`<after>`), the command to go back and where the backups are; it took them before changing
anything. Going back is two separate questions, the code and the database.

1. **Did the update bring migrations?** `git diff --stat <before> <after> -- migrations`.
   - No output: the schema did not change. `git checkout <before> && bash tools/work.sh start --build` is enough
     (`git checkout <your branch>` later, to follow updates again).
   - Files listed: the new code migrated the database when the stack came up, and the old code may not run against the
     migrated schema (the package does not label migrations as safe to go back over). Check out `<before>` and run
     `bash tools/work.sh start --build` so that the old image is built (the stack may not become healthy against the
     migrated schema; that is expected here), then restore the backup set this update took (below), so that code and
     data match. `restore` runs the old image's migration on the restored data.
2. If `start --build` of the old code runs and `bash tools/work.sh status` is healthy, you are done. Nothing needs
   restoring when the database was not migrated or damaged.

## Restoring from a backup

`backup` writes `sidekick-<time>.sql.enc` (plain SQL made with `pg_dump --no-owner`, then encrypted) and
`hindsight-<time>.tar.gz.enc` (the volume as a `tar.gz`, then encrypted), one **backup set** per time stamp. `restore`
needs the same key (`deploy/work/secrets/backup.key`) and decrypts on the way into Postgres and into the volume: no plain
file is written. A set is only restored whole, because Sidekick's database records which sources were sent to
Hindsight and Hindsight keeps the memories themselves. The backups hold no passwords and the secrets in
`deploy/work/secrets/` are not part of them: the roles and their passwords belong to the Postgres volume, so a restore
works with whatever secrets the running stack has. The owner `jobb` is part of the dump.

```bash
bash tools/work.sh restore                          # lists the complete sets in deploy/work/backups/
bash tools/work.sh restore 20261110-142500          # dry run: checks the set and prints the plan, changes nothing
bash tools/work.sh restore 20261110-142500 --apply  # restores; asks you to type the project name (sidekick-work)
```

Instead of a time stamp you can give the path to either file of a set, for example a set copied from another machine.
Without `--apply` the command only reads: it checks that both files exist, that the key is there, that both files can
be decrypted with it, that the dump is complete (it ends with pg_dump's end marker) and that the archive can be read and
is not empty, that the memory volume exists, and prints the plan. With `--apply` it does nothing until you type the project name, and then:

1. takes a fresh backup of what is there now into `deploy/work/backups/` (the way back; nothing is pruned),
2. pauses the `api`, the `memory-worker` and the `automation-worker` (this also ends Claude Desktop's session),
3. renames the database `sidekick` to `sidekick_before_restore_<time>` (it is kept, not dropped), creates a new `sidekick`
   with the grants the package's role bootstrap gives, reads the dump into it in one transaction and gives every object
   its owner back (`deploy/selfhost/restore-ownership.sql`; without it the migrator could not change the tables in a later
   update),
4. stops Hindsight, empties its volume and unpacks the archive into it (offline, with the pinned Hindsight image),
5. runs the migration, so that a set from older code is brought up to the schema of the image you run,
6. starts Hindsight and the writers, waits until the api is ready (the database answers and the schema is at the image's
   revision), points Claude Desktop's configuration at the restored `jobb` user and rewrites it.

**When something fails.**

- The set is missing a file, the key is missing or wrong, a file is damaged or has been changed (the encryption is
  authenticated, so one flipped bit is refused), the dump is cut off, the archive is broken or empty, the memory volume
  does not exist (run `start` first), or you do not type the project name: the command stops and nothing is changed.
- Another changing command (for example `start`, `backup` or `update`) is running: `restore` is refused and nothing is
  changed. Run it again when the other one has finished.
- The fresh backup in step 1 fails, `docker compose ps` cannot tell which writers are running, or a writer is still
  running after the stop: it stops before anything is changed, and the writers it stopped are started again.
- Step 3, 4 or 5 fails, or the command is interrupted (Ctrl-C, a closed terminal) during them: the memory is unpacked
  again from the fresh backup of step 1, the new database is dropped and `sidekick_before_restore_<time>` gets its old name
  back, and then Hindsight and the writers start. The message says "What was there before is back". This also holds
  when the interruption comes right after the rename: putting back asks Postgres which of the two names exist, so it
  is right whether the rename ran or not, and running it twice changes nothing.
- Putting back fails as well: nothing is started (the memory-worker would otherwise start Hindsight on a volume in an
  unknown state). The message names the log (`deploy/work/work.log`), the name of the previous database and the fresh
  backup set. Read the log, then restore that fresh set with `restore <its time> --apply`; if the database was not
  renamed back, do that first:
  `docker exec sidekick-work-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE IF EXISTS sidekick" -c "ALTER DATABASE sidekick_before_restore_<time> RENAME TO sidekick"`.
- The services do not start or the api does not become ready after step 6: nothing is rolled back, because the services
  have already run against the restored data. The previous database and the fresh backup are kept and named in the
  message; read the log, and restore the fresh set if you want to go back.

When everything worked, ask Claude Desktop for something you know is in the restored data. When you are sure, free
the space with the command the restore prints:
`docker exec sidekick-work-postgres-1 psql -U postgres -d postgres -c "DROP DATABASE sidekick_before_restore_<time>"`.

On a new machine: `setup` or `init` and `start` first (they create the roles, a new `jobb` user and the memory volume),
copy the set **and the backup key** there (put the key at `deploy/work/secrets/backup.key`), then
`restore <path to the set's .sql.enc file> --apply`. Claude Desktop's configuration is rewritten for
the restored `jobb` user; merge it again as in step 4 of [Steps](../../start/work-laptop.md#steps).
