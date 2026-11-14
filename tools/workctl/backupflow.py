"""The backup of ``work.sh backup``, ``update`` and ``restore``: the database (pg_dump) and Hindsight's memory.

Hindsight keeps its data in an embedded Postgres in the volume ``hindsight_pg0`` (deploy/selfhost/compose.yaml); a copy
of live database files is not consistent, so Hindsight is stopped for the few seconds the volume is archived (tar, run
from the pinned Hindsight image itself, offline) and started again. The services that write to Postgres or feed
Hindsight are paused for the whole backup, so the dump and the archive describe the same moment. Both files get the
same time stamp. If either fails, nothing is kept and the caller stops.

The files are encrypted with the key of ``backupkey`` (the mechanism of the encrypted snapshots of
deploy/selfhost/update.sh, run in a one-off api container). No plain dump or archive is written to disk: pg_dump and tar
are piped straight into the encryption. A backup counts only after it was decrypted and checked again.

``Backup`` leaves the cleanup to the command that uses it: whatever way that command ends, it calls ``abort`` unless it
finished, and ``abort`` starts everything again and removes half-made files.
"""

from __future__ import annotations

import contextlib
import re
from pathlib import Path

from . import backupfiles, backupkey, worklock
from .stack import Stack, Stage, Stop

WRITERS = ("api", "memory-worker", "automation-worker")
# The exact form of a finished backup file: only such names are measured and pruned.
DB_ERE = r"sidekick-[0-9]{8}-[0-9]{6}\.sql\.enc"
MEM_ERE = r"hindsight-[0-9]{8}-[0-9]{6}\.tar\.gz\.enc"
DEFAULT_KEEP = "7"
DUMP_END = b"PostgreSQL database dump complete"
START_TIMEOUT = "300"


def keep_setting(stack: Stack) -> str:
    return stack.environ.get("SIDEKICK_WORK_KEEP_BACKUPS", DEFAULT_KEEP)


def _first_line(text: str | None) -> str:
    lines = (text or "").splitlines()
    return lines[0] if lines else ""


def _create_private(path: Path) -> bool:
    """The encrypted file is created private (0600) before a byte is written, whatever the umask."""
    try:
        path.write_bytes(b"")
        path.chmod(0o600)
    except OSError:
        return False
    return True


class Backup:
    """One backup of the stack. The files of the finished set are ``db`` and ``mem`` (None when the memory is off)."""

    def __init__(self, stack: Stack, keep: str) -> None:
        self.stack = stack
        self.keep = keep
        self.paused: list[
            str
        ] = []  # the writers that were running when the backup began; started again on every way out
        self.hindsight_paused = False
        self.partial: list[Path] = []  # files that are removed unless the backup finished
        self.stamp = ""
        self.db: Path | None = None
        self.mem: Path | None = None

    # -- the checks before anything is changed ---------------------------------------------------------------

    def preflight(self) -> None:
        """Fails closed (nothing is paused or started): a bad number of sets to keep, too little room."""
        stack = self.stack
        stack.backups.mkdir(parents=True, exist_ok=True)
        stack.backups.chmod(0o700)
        if not backupfiles.valid_keep(self.keep):
            stack.errf("bk_keep_bad", self.keep)
            raise Stop(1)
        check = backupfiles.check_space(stack.backups, stack.environ, [DB_ERE, MEM_ERE])
        if check.outcome == backupfiles.TOO_LITTLE:
            stack.errf("bk_space", stack.backups, check.free, check.needed)
            raise Stop(1)
        if check.outcome == backupfiles.UNKNOWN:
            stack.errf("bk_space_unknown", stack.backups)
            raise Stop(1)
        self.require_key(generate=True)

    def require_key(self, generate: bool = False) -> None:
        """Fails closed unless a usable key file exists. A missing key is never replaced silently while encrypted
        backups exist: a new key would make them unreadable. ``generate`` creates the key when there is no backup."""
        stack = self.stack
        try:
            created = backupkey.ensure_key(stack.backup_key_file, stack.backups, generate)
        except backupkey.KeyProblem as problem:
            stack.errf(problem.key, *problem.values)
            raise Stop(1) from None
        if created:
            stack.sayf("bk_key_new", stack.backup_key_file)

    # -- the writers ------------------------------------------------------------------------------------------

    def pause_writers(self, message: str = "bk_writers_pause") -> bool:
        """Stops every writer that is or may become active, then checks that none is and none can start again by
        itself. Fails closed: False (the caller aborts before changing anything, ``abort`` starts the paused ones
        again) if compose or docker cannot tell which writers are active, if the stop fails, or if any writer is
        still active afterwards."""
        stack = self.stack
        names = " ".join(WRITERS)
        self.paused = []
        for service in WRITERS:
            live = stack.live_containers(service)
            if live is None:
                stack.errf("writers_unknown", names, stack.log)
                return False
            if live:
                self.paused.append(service)
        if self.paused:
            stack.sayf(message, " ".join(self.paused))
            if not stack.compose("stop", *self.paused):
                return False
        for service in WRITERS:
            live = stack.live_containers(service)
            if live is None:
                stack.errf("writers_unknown", names, stack.log)
                return False
            if live:
                stack.errf("writers_still", names)
                return False
        return True

    def resume_writers(self) -> bool:
        """Starts the paused writers again (waits until healthy); idempotent, the list is emptied only on success."""
        if not self.paused:
            return True
        if self.stack.compose("up", "-d", "--wait", "--wait-timeout", START_TIMEOUT, *self.paused):
            self.paused = []
            return True
        return False

    def resume_hindsight(self) -> bool:
        """Starts Hindsight again (also the way out of a pause, see ``memory``)."""
        if not self.hindsight_paused:
            return True
        # The gateway depends on the api: do not restart paused writers through Hindsight's dependencies.
        if self.stack.compose("up", "-d", "--wait", "--wait-timeout", START_TIMEOUT, "--no-deps", "hindsight"):
            self.hindsight_paused = False
            return True
        return False

    def abort(self) -> None:
        """The cleanup for every way out: an interrupt (Ctrl-C, a closed terminal, kill) or an unexpected error
        cannot leave the memory or the writers stopped, and no half-made backup files are kept."""
        self.stack.signals.defer()
        for path in self.partial:
            with contextlib.suppress(OSError):
                path.unlink()
        self.resume_hindsight()
        self.resume_writers()

    # -- the files --------------------------------------------------------------------------------------------

    def _verified(self, stages: list[Stage], path: Path, found: re.Pattern[bytes]) -> bool:
        """The proof that a backup is usable: decrypted again (the encryption authenticates the whole file, so a
        damaged or wrongly keyed file fails), and what is inside looks right. Nothing is written to disk."""
        hit = [False]

        def scan(line: bytes) -> None:
            if found.search(line):
                hit[0] = True

        with path.open("rb") as source:
            ok = self.stack.pipeline(stages, stdin=source, scan=scan)
        return ok and hit[0]

    def verify_dump(self, path: Path) -> bool:
        decrypt = self.stack.crypto("decrypt")
        return decrypt is not None and self._verified([decrypt], path, re.compile(re.escape(DUMP_END)))

    def verify_archive(self, path: Path) -> bool:
        decrypt = self.stack.crypto("decrypt")
        listing = Stage(["tar", "-tz"], self.stack.environ)
        return decrypt is not None and self._verified([decrypt, listing], path, re.compile(rb"[^\n]"))

    def _encrypt_into(self, producer: Stage, part: Path) -> bool:
        """``producer | encrypt`` into ``part``; False when it failed or wrote nothing."""
        encrypt = self.stack.crypto("encrypt")
        if encrypt is None:
            return False
        with part.open("wb") as target:
            ok = self.stack.pipeline([producer, encrypt], stdout=target)
        return ok and part.stat().st_size > 0

    def _publish(self, part: Path, out: Path) -> None:
        """Verified, so now durable: flush the file, rename it into place, flush the directory entry."""
        part.chmod(0o600)
        self.stack.fsync(part)
        part.rename(out)
        self.stack.fsync(self.stack.backups)

    def database(self, out: Path) -> bool:
        stack = self.stack
        part = out.with_name(out.name + ".part")
        if not _create_private(part):
            return False
        dump = Stage(
            stack.compose_argv(["exec", "-T", "postgres", "pg_dump", "-U", "postgres", "-d", "sidekick", "--no-owner"]),
            stack.compose_env(),
        )
        if not self._encrypt_into(dump, part):
            part.unlink(missing_ok=True)
            return False
        if not self.verify_dump(part):
            stack.errf("bk_verify_fail", out, stack.log)
            part.unlink(missing_ok=True)
            return False
        self._publish(part, out)
        return True

    def memory(self, out: Path | None) -> bool:
        """Archive the volume into ``out``. True when there is nothing to archive; False on any failure, after
        Hindsight has been started again."""
        stack = self.stack
        if not stack.memory or out is None:
            stack.say("bk_mem_off")
            return True
        volume = stack.hindsight_volume()
        if not volume:
            stack.say("bk_mem_none")
            return True
        image = stack.hindsight_image()
        if not image:
            return False
        stack.say("bk_mem_pause")
        part = out.with_name(out.name + ".part")
        self.partial.insert(0, part)
        if not _create_private(part):
            part.unlink(missing_ok=True)
            return False
        self.hindsight_paused = True
        archive = Stage(
            [
                "docker",
                "run",
                "--rm",
                "--network",
                "none",
                "-v",
                f"{volume}:/src:ro",
                "--entrypoint",
                "tar",
                image,
                "-C",
                "/src",
                "-czf",
                "-",
                ".",
            ],
            stack.environ,
        )
        ok = stack.compose("stop", "hindsight") and self._encrypt_into(archive, part)
        if not ok:
            part.unlink(missing_ok=True)
        if not self.resume_hindsight():
            ok = False
        # Hindsight is up again; only now the (slower) read-back of the encrypted archive.
        if ok and not self.verify_archive(part):
            stack.errf("bk_verify_fail", out, stack.log)
            part.unlink(missing_ok=True)
            ok = False
        self.partial.remove(part)
        if not ok:
            return False
        self._publish(part, out)
        stack.sayf("bk_mem_ok", out)
        return True

    # -- the whole backup -------------------------------------------------------------------------------------

    def take(self) -> None:
        """Pause the writers, dump the database, archive Hindsight (paused inside) and leave the writers paused. The
        set is in ``stamp``, ``db`` and ``mem``. Any failure ends the command with status 1."""
        stack = self.stack
        self.preflight()
        if not stack.container_id("postgres") and not stack.compose("up", "-d", "--wait", "postgres"):
            stack.errf("bk_db_start", stack.log)
            raise Stop(1)
        stamp = backupfiles.next_stamp(stack.backups)
        db = stack.backups / f"sidekick-{stamp}.sql.enc"
        mem = stack.backups / f"hindsight-{stamp}.tar.gz.enc" if stack.memory else None
        if not self.pause_writers():
            stack.errf("bk_fail", stack.log)
            raise Stop(1)
        self.partial = [db.with_name(db.name + ".part")]
        if not self.database(db):
            stack.errf("bk_fail", stack.log)
            raise Stop(1)
        stack.sayf("bk_db_ok", db)
        self.partial = [db]
        if not self.memory(mem):
            stack.errf("bk_fail", stack.log)
            raise Stop(1)
        self.partial = []
        self.stamp, self.db, self.mem = stamp, db, mem

    def prune(self) -> None:
        """Keeps the newest ``keep`` of each kind and never deletes the files of the set just written. Does nothing
        when the newest set is not there, so a failed backup never prunes older ones."""
        stack = self.stack
        if self.db is None or not self.db.is_file() or self.db.stat().st_size == 0:
            return
        keep = int(self.keep)
        backupfiles.prune(stack.backups, keep, DB_ERE, self.db.name)
        backupfiles.prune(stack.backups, keep, MEM_ERE, self.mem.name if self.mem else "")
        stack.fsync(stack.backups)


def run_backup(stack: Stack) -> int:
    """``work.sh backup``, under the lock."""
    return worklock.run_locked(stack, "backup", lambda: _backup(stack))


def _backup(stack: Stack) -> int:
    """Pause the writers, take both copies, start everything again, prune the old sets. Returns
    the exit status."""
    backup = Backup(stack, keep_setting(stack))
    finished = False
    code = 0
    with stack.caught_signals():
        try:
            backup.take()
            # The cleanup stays armed until the writers are up: a TERM during the restart still ends in a second,
            # harmless attempt.
            if not backup.resume_writers():
                stack.errf("bk_writers_fail", " ".join(WRITERS), stack.log)
                raise Stop(1)
            finished = True
            backup.prune()
            stack.sayf("bk_keep", backup.keep, stack.backups)
        except Stop as stop:
            code = stop.code
        finally:
            if not finished:
                backup.abort()
                code = stack.signals.settle(code)
    return code
