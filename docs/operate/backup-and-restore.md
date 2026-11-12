# Backup and restore

[Svenska](backup-and-restore.sv.md)

<!-- description: Take encrypted backups of your data and read them back. Keep the key and a copy of the backups somewhere other than the server. -->

Take encrypted backups of your data and read them back. Keep the key and a copy of the backups somewhere other than the server.

What each copy holds:

| Copy | Made by | Holds | Restore with |
| --- | --- | --- | --- |
| Encrypted owner backup (`.skbackup`) | `--profile backup`, and `update.sh --apply` | one or more owners' data, as an export | `restore.sh` (`sidekick-backup import`) |
| Encrypted database snapshot | `update.sh --apply`, in `update-state/snapshots/` | the whole database | the steps below |
| Hindsight memory | nothing automatic | the `hindsight_pg0` volume | the steps below |

**Owner backups.** Create the key and put it in `selfhost.env` as `SIDEKICK_BACKUP_ENCRYPTION_KEY`, then start the
profile. Keep a copy of the key somewhere other than this machine: without it neither the backups nor the update
snapshots can be read.

```bash
docker compose --env-file selfhost.env run --rm --no-deps api sidekick-backup keygen
docker compose --env-file selfhost.env --profile backup up -d
```

The files appear in `/var/lib/sidekick/backups` in the `state` volume, with the retention set in `selfhost.env`. Copy
them off the machine:

```bash
mkdir -p backups && docker compose --env-file selfhost.env --profile backup cp backup:/var/lib/sidekick/backups/. ./backups/
```

**Free space and pruning.** A new owner backup, and the snapshot of `update.sh --apply`, are written only when the
directory has room: at least the size of the newest finished one times `SIDEKICK_BACKUP_SPACE_MARGIN_PCT` (default 150,
at least 100) and at least 64 MiB. For the snapshot, `update.sh` reads the floor from its own environment as
`SIDEKICK_BACKUP_SPACE_FLOOR_MB` (default 64). The first one has nothing to compare with, so
only the floor applies. Otherwise the command refuses with a clear message; `update.sh` checks this **before** it stops
anything (journal `ABORTED`, nothing touched), and a free size it cannot read counts as a refusal. Owner backups keep at
least the newest `SIDEKICK_BACKUP_MIN_KEEP` (default 5) finished files, however old, on top of the count and age
limits. `update.sh` prunes snapshots only after a **successful** update, keeps the newest `SIDEKICK_SNAPSHOT_KEEP`
(default 5, read from its own environment) and never the one it just took. Pruning only ever touches files whose whole
name is the finished form (`sidekick-pre-<UTC time>.dump.enc`, `sidekick-backup-<UTC time>-<id>.skbackup`), never a
`.partial`, a hidden file, a symlink or anything else you put there.

**Size ceiling.** An owner backup holds at most 512 MiB of plaintext: a larger one is refused when it is created (a
safe log line, nothing written), and `sidekick-backup import` refuses a larger backup or export before it reads it. A
backup over 512 MiB of plaintext written before this ceiling existed cannot be imported, and there is deliberately no
setting to raise it. The ceiling is applied while the export is read, so an oversize backup is refused after about that much data and
not after the whole database has been loaded. Encryption is not streaming (the backup is one Fernet token), so a backup
just under the ceiling is still held in memory, and a few copies of it, while it is encrypted and read back.

**Restore one owner** from a `.skbackup` file (or a plain owner export `.json`) into an existing, empty owner (create
it first with `sidekick-admin create-user`, step 3 of [First start](../start/self-hosted-server.md#first-start)). `restore.sh` is a thin wrapper
around `sidekick-backup import` in a one-off `api` container. It shows the plan and writes nothing without `--apply`;
with `--apply` it writes exactly the plan it just showed (matched by its checksum) and checks the row counts. A target
owner that already holds data is refused, and so is a wrong key or a changed plan. Only backups and exports in the
current format are read; older backups and owner exports are not. Without the wrapper, use `sidekick-backup import`:

```bash
./restore.sh --backup FILE.skbackup --target-owner UUID [--source-owner UUID]           # plan only
./restore.sh --backup FILE.skbackup --target-owner UUID [--source-owner UUID] --apply
```

For a backup from an earlier installation, the key must be the one that installation encrypted it with, not the new key from `keygen` above, which cannot decrypt it. The key is read from `SIDEKICK_BACKUP_ENCRYPTION_KEY` in `selfhost.env` (or from `--key-file` below); a plain `.json` export needs no key. Without
the wrapper, run the command yourself and apply in a second step with the checksum the plan printed (`FILE` of `-`
reads standard input; `--key-file PATH` reads the key from a file with mode 600 instead of the environment):

```bash
sidekick-backup import FILE --target-owner UUID [--source-owner UUID]
sidekick-backup import FILE --target-owner UUID [--source-owner UUID] --apply --plan-checksum SHA256
```

**Restore the whole database** from an update snapshot (for example after a bad migration). The snapshot is a
`pg_dump -Fc` file that includes owners, so no repair is needed afterwards. The old database is renamed, not deleted:

```bash
(umask 077; ./update.sh --decrypt-snapshot update-state/snapshots/<file>.dump.enc > snapshot.dump)
# The snapshot is from before the update, so start the image that ran then, not the new one in release.env.
# update.sh writes it into the journal when the update starts; release.env is not reliable here, because after a
# failed migration it has not been rewritten yet and may name the image before the one before.
PREV="$(grep ' STARTED ' update-state/journal.log | tail -n 1 | sed -n 's/.* previous=\([^ ]*\).*/\1/p')"
export SIDEKICK_API_IMAGE="${PREV:-roadlake-sidekick:selfhost}"
C="docker compose --env-file selfhost.env"        # no release.env here
$C --profile backup --profile push --profile memory stop api automation-worker backup push memory-worker
PG="$C exec -T postgres psql -U postgres -v ON_ERROR_STOP=1 -q"
$PG -d postgres -c "ALTER DATABASE sidekick RENAME TO sidekick_before_restore"
$PG -d postgres <<'SQL'
CREATE DATABASE sidekick;
GRANT CONNECT ON DATABASE sidekick TO sidekick_migrator, sidekick_app;
GRANT CREATE ON DATABASE sidekick TO sidekick_owner;
SQL
$PG -d sidekick -c "GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator"
$C exec -T postgres pg_restore -U postgres -d sidekick --exit-on-error --single-transaction < snapshot.dump
$C --profile vps up -d                                            # with the profiles you use
```

When the restored installation answers, make the files agree with it. `release.env` goes back to the previous image
(it is removed when that was a local build), and the journal records the restore so that the next update is allowed:

```bash
case "$PREV" in *@sha256:*) printf 'SIDEKICK_API_IMAGE=%s\n' "$PREV" > release.env ;; *) rm -f release.env ;; esac
echo "$(date -u +%Y-%m-%dT%H:%M:%SZ) ROLLED_BACK manual-restore" >> update-state/journal.log
```

If a step fails, drop the new database and rename `sidekick_before_restore` back. When the restored installation
checks out, `$PG -d postgres -c "DROP DATABASE sidekick_before_restore"` frees the space. The decrypted `snapshot.dump`
holds all your data in clear: it was written readable by you only, so delete it (or keep it on encrypted storage) when
you are done. The restore commands were run against a scratch PostgreSQL set up with `postgres-init.sh`; the result had
the same owners and grants as the original. A snapshot is a dump of one moment: the `state` volume (OAuth client
storage) is not in it, and signed-in clients may have to sign in again.

**Hindsight memory** is not in any of the copies above. To archive it by hand, stop Hindsight for a moment and tar the
volume from the pinned image itself. This archive is not encrypted: it holds the whole memory in clear, so it is written
readable by you only (`umask 077`); keep it on encrypted storage. `tools/work.sh backup` (the work package) makes the same
copy but encrypts it with its own key, as `hindsight-<time>.tar.gz.enc`, so use that if you run the work package:

```bash
C="docker compose --env-file selfhost.env --profile memory"
$C stop hindsight
(umask 077; docker run --rm --network none -v sidekick_hindsight_pg0:/src:ro \
  --entrypoint tar "$($C config --images | grep vectorize-io/hindsight)" -C /src -czf - . > hindsight-$(date +%Y%m%d).tar.gz)
$C up -d hindsight
```

To restore the archive, stop everything that uses the memory, empty the volume and unpack the archive into it with the
same pinned image, then start again. Check that `docker volume ls` shows `sidekick_hindsight_pg0` and that the image
printed by the first command is the Hindsight image you run; the empty-and-unpack step deletes what is in the volume:

```bash
C="docker compose --env-file selfhost.env --profile memory"
$C stop api memory-worker hindsight
$C config --images | grep vectorize-io/hindsight
docker run --rm -i --network none -v sidekick_hindsight_pg0:/dst --entrypoint sh \
  "$($C config --images | grep vectorize-io/hindsight)" \
  -c 'find /dst -mindepth 1 -delete && tar -C /dst -xzf -' < hindsight-YYYYMMDD.tar.gz
$C up -d hindsight memory-worker api               # with --profile vps if you use it
```

Check that Hindsight becomes healthy (`docker compose --env-file selfhost.env --profile memory ps`) and that the
memory answers in Claude. The [release drill](../maintainers/release-drill.md) runs both directions against a real Hindsight volume (a marker file in it, not a memory bank read back through Hindsight).
