"""``work.sh restore``: the database and Hindsight's memory from ONE backup set (the same time stamp), never one without
the other, because Sidekick's database records which sources were sent to Hindsight and Hindsight holds the memories.

Without ``--apply`` it checks the set and the target and prints the plan; it reads only. With ``--apply``, after the
project name is typed: a backup of what is there now (the way back; the writers stay paused), the database ``sidekick``
is renamed (kept, not dropped) and the dump read into a fresh one with the grants postgres-init.sh gives, ownership
repaired, Hindsight stopped and its volume replaced, the migration run. Until that point every failure or interrupt puts
the previous database and memory back (``Restore.abort``). Then Hindsight and the writers start and the api must become
ready; from there nothing is rolled back automatically, because the services have run against the restored data.
"""

from __future__ import annotations

import contextlib
import sys
from pathlib import Path

from . import desktopsetup, messages, owner, prompts, restore, stackstate, worklock
from .backupflow import Backup, keep_setting
from .readiness import wait_ready
from .stack import Stack, Stage, Stop

NO_OTHER_SESSIONS = (
    "SELECT pg_terminate_backend(pid) FROM pg_stat_activity WHERE datname = 'sidekick' AND pid <> pg_backend_pid()"
)
OWNER_QUERY = "select id from sidekick.users where username = 'jobb'"
# Empties the volume and unpacks the archive on stdin into it.
UNPACK = "find /dst -mindepth 1 -delete && tar -C /dst -xzf -"
USAGE_EXIT = 2


def _nonempty(path: Path | None) -> bool:
    return path is not None and path.is_file() and path.stat().st_size > 0


def print_sets(stack: Stack) -> None:
    """The complete backup sets of the backup directory, on stderr: what a restore can name."""
    stamps = restore.complete_sets(stack.backups, stack.memory)
    if not stamps:
        print(messages.fill(stack.lang, "rs_no_sets", stack.backups), file=sys.stderr)
        return
    print(messages.fill(stack.lang, "rs_sets", stack.backups), file=sys.stderr)
    for stamp in stamps:
        print(f"  {stamp}", file=sys.stderr)


class Restore:
    def __init__(self, stack: Stack) -> None:
        self.stack = stack
        self.backup = Backup(stack, keep_setting(stack))
        self.old_db = ""  # the name the previous database gets (set just before the rename); empty = nothing to undo
        self.old_name = ""  # the same name, kept for the messages
        self.memory_touched = False  # the memory volume may hold something other than what was there before
        self.committed = False  # the restored data is final: from then on the cleanup only starts services again
        self.safety_db: Path | None = None
        self.safety_mem: Path | None = None

    # -- the set -----------------------------------------------------------------------------------------------

    def check_set(self, db: Path, mem: Path) -> bool:
        """Both files present and whole, read with the key: decrypted again, the dump ends with pg_dump's end marker
        and the archive lists and holds at least one entry. A missing key stops here (fail closed), before anything
        is changed."""
        stack = self.stack
        if not _nonempty(db):
            stack.errf("rs_missing", db)
            return False
        if stack.memory and not _nonempty(mem):
            stack.errf("rs_missing", mem)
            return False
        self.backup.require_key()
        if not self.backup.verify_dump(db):
            stack.errf("rs_bad_dump", db, stack.backup_key_file)
            return False
        if stack.memory and not self.backup.verify_archive(mem):
            stack.errf("rs_bad_archive", mem, stack.backup_key_file)
            return False
        return True

    # -- the swap ----------------------------------------------------------------------------------------------

    def _psql(self, *args: str) -> bool:
        return self.stack.compose(*self.stack.pg_admin(*args))

    def restore_database(self, dump: Path, old: str) -> bool:
        """Renames sidekick to ``old`` and reads the encrypted dump into a fresh sidekick (decrypted on the way, never
        to disk). False on any failure (the cleanup undoes it)."""
        stack = self.stack
        if not self._psql("-d", "postgres", "-c", NO_OTHER_SESSIONS):
            return False
        # Recorded before the rename: a signal between the rename and the next line must still find the way
        # back. ``rollback_database`` asks Postgres which of the two names exist, so it is right whether the
        # rename ran or not.
        self.old_db = old
        if not self._psql("-d", "postgres", "-c", f"ALTER DATABASE sidekick RENAME TO {old}"):
            return False
        created = self._psql(
            "-d",
            "postgres",
            "-c",
            "CREATE DATABASE sidekick",
            "-c",
            "GRANT CONNECT ON DATABASE sidekick TO sidekick_migrator, sidekick_app",
            "-c",
            "GRANT CREATE ON DATABASE sidekick TO sidekick_owner",
        )
        if not created or not self._psql(
            "-d", "sidekick", "-c", "GRANT CREATE, USAGE ON SCHEMA public TO sidekick_migrator"
        ):
            return False
        decrypt = stack.crypto("decrypt")
        if decrypt is None:
            return False
        # VERBOSITY=sqlstate: psql prints only the error code. Its normal messages quote the failing row ("Failing row
        # contains", COPY context lines, the rejected value), and the last lines of the log are shown on failure.
        load = Stage(
            stack.compose_argv(stack.pg_admin("-v", "VERBOSITY=sqlstate", "-d", "sidekick", "--single-transaction")),
            stack.compose_env(),
        )
        with dump.open("rb") as source, stack.log.open("ab") as log:
            if not stack.pipeline([decrypt, load], stdin=source, stdout=log):
                return False
        # The dump leaves out owners; without this the migrator could not change the tables in a later update.
        with (stack.selfhost / "restore-ownership.sql").open("rb") as ownership:
            return stack.compose_stdin(ownership, *stack.pg_admin("-d", "sidekick"))

    def unpack_memory(self, archive: Path) -> bool:
        """Empties the Hindsight volume and unpacks the encrypted archive into it (decrypted on the way, never to disk),
        offline, with the pinned image. Hindsight must be stopped."""
        stack = self.stack
        volume, image = stack.hindsight_volume(), stack.hindsight_image()
        decrypt = stack.crypto("decrypt")
        if not volume or not image or decrypt is None:
            return False
        docker_run = ["docker", "run", "--rm", "-i", "--network", "none", "-v", f"{volume}:/dst"]
        unpack = Stage([*docker_run, "--entrypoint", "sh", image, "-c", UNPACK], stack.environ)
        with archive.open("rb") as source, stack.log.open("ab") as log:
            return stack.pipeline([decrypt, unpack], stdin=source, stdout=log)

    def rollback_database(self) -> bool:
        """Idempotent, decided by what exists: the old name present means the rename ran (drop the new sidekick, rename
        back); only sidekick present means the rename never ran or was undone already (nothing to do); neither, or no
        answer from Postgres, is a failure (the cleanup then starts nothing)."""
        if not self.old_db:
            return True
        query = f"SELECT datname FROM pg_database WHERE datname IN ('sidekick', '{self.old_db}')"  # noqa: S608 - made here
        names = self.stack.compose_read(*self.stack.pg_admin("-d", "postgres", "-tAc", query))
        if names is None:
            return False
        action = restore.rollback_action(names.split(), self.old_db)
        if action == restore.RENAME_BACK:
            renamed = self._psql(
                "-d",
                "postgres",
                "-c",
                NO_OTHER_SESSIONS,
                "-c",
                "DROP DATABASE IF EXISTS sidekick",
                "-c",
                f"ALTER DATABASE {self.old_db} RENAME TO sidekick",
            )
            if not renamed:
                return False
        elif action != restore.KEEP:
            return False
        self.old_db = ""
        return True

    def rollback_memory(self) -> bool:
        if not self.memory_touched:
            return True
        if self.safety_mem is not None and self.unpack_memory(self.safety_mem):
            self.memory_touched = False
            return True
        return False

    def abort(self) -> None:
        """The cleanup for every way out. Before the commit point: put the previous memory and database back (Hindsight
        is still stopped), then start Hindsight and the writers again. After it: only start them again. If putting back
        fails, nothing is started (the memory worker would start Hindsight on a volume in an unknown state); the message
        says what is where."""
        stack = self.stack
        stack.signals.defer()
        for path in self.backup.partial:
            with contextlib.suppress(OSError):
                path.unlink()
        if not self.committed:
            undone = bool(self.old_db) or self.memory_touched
            restored = self.rollback_memory()
            restored = self.rollback_database() and restored
            if not restored:
                stack.errf("rs_rollback_fail", stack.log, self.old_name, self.safety_db or "", self.safety_mem or "")
                return
            if undone:
                stack.errf("rs_rolled_back", self.old_name, self.safety_mem or "")
        self.backup.resume_hindsight()
        self.backup.resume_writers()

    # -- the steps ---------------------------------------------------------------------------------------------

    def _failed(self, step: str) -> Stop:
        self.stack.errf("rs_fail", messages.text(self.stack.lang, step), self.stack.log)
        return Stop(1)

    def apply(self, db: Path, mem: Path, stamp: str) -> None:
        """The restore itself, after the person has typed the project name."""
        stack, backup = self.stack, self.backup
        stack.mark(f"restore {stamp}")
        # 1-2. The way back, taken while the writers are paused; they stay paused.
        backup.take()
        self.safety_db, self.safety_mem = backup.db, backup.mem
        self.old_name = stackstate.old_database_name(backup.stamp)
        if stack.memory and not _nonempty(self.safety_mem):
            stack.errf("bk_fail", stack.log)
            raise Stop(1)
        none = messages.text(stack.lang, "mem_off_word")
        stack.sayf("rs_safety", self.safety_db, self.safety_mem or none)
        # 3. The database.
        stack.sayf("rs_db", self.old_name)
        if not self.restore_database(db, self.old_name):
            raise self._failed("rs_step_db")
        # 4. The memory.
        if stack.memory:
            stack.say("rs_mem")
            backup.hindsight_paused = True
            if not stack.compose("stop", "hindsight"):
                raise self._failed("rs_step_mem")
            self.memory_touched = True
            if not self.unpack_memory(mem):
                raise self._failed("rs_step_mem")
        # 5. A set from older code is brought up to the schema of this image (yoyo is idempotent).
        stack.say("rs_migrating")
        if not stack.compose("run", "--rm", "-T", "--no-deps", "migrate"):
            raise self._failed("rs_step_migrate")
        # 6. Commit point: the restored data is final; the cleanup now only starts the services again.
        self.committed = True
        if not backup.resume_hindsight() or not backup.resume_writers():
            stack.errf("rs_start_fail", stack.log, self.old_name, self.safety_db or "", self.safety_mem or "")
            raise Stop(1)
        if not wait_ready(stack):
            stack.errf("rs_ready_fail", stack.log, self.old_name, self.safety_db or "", self.safety_mem or "")
            raise Stop(1)

    def sync_owner(self) -> None:
        """The restored database has its own owner user jobb (on another machine a different UUID): point Claude Desktop
        at it."""
        stack = self.stack
        user_id = stack.db_scalar(OWNER_QUERY) or ""
        if owner.is_uuid(user_id):
            desktopsetup.publish_owner(stack, user_id)
        else:
            stack.say("rs_owner_none")
            desktopsetup.drop_owner(stack)


def run_restore(stack: Stack, reference: str, apply: bool) -> int:
    """Returns the exit status; ``--apply`` runs under the lock."""
    return worklock.run_locked(stack, "restore --apply", lambda: _restore(stack, reference, apply), needed=apply)


def _restore(stack: Stack, reference: str, apply: bool) -> int:
    if not reference:
        stack.errf("rs_usage")
        print_sets(stack)
        return USAGE_EXIT
    ref = restore.parse_reference(reference, str(stack.backups))
    if ref is None:
        stack.errf("rs_bad_name", reference)
        return USAGE_EXIT
    db = Path(ref.directory) / f"sidekick-{ref.timestamp}.sql.enc"
    mem = Path(ref.directory) / f"hindsight-{ref.timestamp}.tar.gz.enc"
    job = Restore(stack)
    code = 0
    finished = False
    with stack.caught_signals():
        try:
            if not job.check_set(db, mem):
                raise Stop(1)
            ownership = stack.selfhost / "restore-ownership.sql"
            if not ownership.is_file():
                stack.errf("rs_no_ownership", ownership)
                raise Stop(1)
            if stack.memory and not stack.hindsight_volume():
                stack.errf("rs_no_volume", stack.project)
                raise Stop(1)
            stack.sayf(
                "rs_plan",
                db,
                mem if stack.memory else messages.text(stack.lang, "mem_off_word"),
                stack.project,
                stack.backups,
            )
            if not apply:
                stack.say("rs_dry")
                finished = True
                return 0
            with stack.signals.interruptible():
                answer = prompts.ask(messages.render(stack.lang, "rs_confirm_q", stack.project))
            if answer != stack.project:
                stack.say("aborted")
                raise Stop(1)
            job.apply(db, mem, ref.timestamp)
            finished = True
            job.sync_owner()
            desktopsetup.desktop_setup(stack)
            stack.sayf("rs_done", ref.timestamp, job.old_name, stack.project, job.old_name)
        except Stop as stop:
            code = stop.code
        finally:
            if not finished:
                job.abort()
                code = stack.signals.settle(code)
    return code
