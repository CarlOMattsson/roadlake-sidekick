"""``work.sh update``: bring the checkout and the stack to the newest version, and say what to do when it fails.

Order: tag the previous image, git pull --ff-only, the migration class check (a refusal puts the code back on the
commit it came from), pull/build. None of that touches data or stops anything, so a failure there only puts the code
and the image name back. Then stop every writer and take the backup (they start again from the previous image if it
fails), keep them stopped, migrate, start the api alone and wait until it is ready, then start the rest and check
again. From the migration on a failure leaves the writers stopped, restores nothing automatically and prints where the
backup is and how to go back (docs/operate/work-laptop/backup-and-update.md). Compare deploy/selfhost/update.sh: the
same rule, written there for a pinned image.
"""

from __future__ import annotations

import contextlib
import shutil
import sys

from . import desktopsetup, invocation, secretfiles, stackfiles, stackstate, workenv, worklock
from .backupflow import WRITERS, Backup, keep_setting
from .readiness import wait_ready
from .stack import Stack, Stop

PRE_MIGRATION, MIGRATING = "pre", "migrating"
# The exit status of tools/check-release-migration-class.py when the declared class is too low.
CLASS_TOO_LOW = 1
START_TIMEOUT = "420"


def migration_refusal(status: int) -> str:
    """The message of a migration class check that did not accept: the class is too low (status 1), or the check could
    not be made (anything else)."""
    return "up_contract" if status == CLASS_TOO_LOW else "up_class_fail"


class Update:
    def __init__(self, stack: Stack, allow_breaking: bool, allow: list[tuple[str, int]]) -> None:
        self.stack = stack
        self.allow_breaking = allow_breaking
        self.allow = allow
        self.backup = Backup(stack, keep_setting(stack))
        # pre: nothing has been migrated (every way out puts the previous version back); migrating: the migration has
        # begun or may have (every way out leaves the writers stopped).
        self.phase = PRE_MIGRATION
        self.prev_image = ""  # the image that ran before the update (its id); empty when there was none
        self.prev_tag = ""  # the tag that keeps it: repository:previous
        self.cur_image = ""  # the tag the stack runs from, which `compose build` moves to the new image
        self.built = False  # the build ran, so cur_image may point at the new image
        self.retag_failed = False  # putting the previous image back under cur_image failed
        self.before = (
            ""  # the commit the checkout was on; the code goes back to it on every failure before the migration
        )

    # -- the way back ------------------------------------------------------------------------------------------

    def save_previous_image(self) -> None:
        """The image name the stack runs from and a tag that keeps what runs now, before the build moves the name on."""
        stack = self.stack
        self.cur_image = invocation.api_image(stack.work_env, stack.environ)
        found = stack.docker_read("image", "inspect", "-f", "{{.Id}}", self.cur_image, quiet=True)
        self.prev_image = (found or "").rstrip("\n")
        if not self.prev_image:
            return
        self.prev_tag = stackstate.previous_image_tag(self.cur_image)
        if stack.docker("tag", self.prev_image, self.prev_tag):
            stack.sayf("up_prev_saved", self.prev_tag)
        else:
            self.prev_image = self.prev_tag = ""

    def abort(self) -> None:
        """The cleanup for every way out. Before the migration: the code goes back to the commit it came from, the
        previous image is put back under its name (a build may have moved it) and the writers, if the backup had
        stopped them, start again from it. From the migration on, the writers stay stopped and nothing is restored: the
        person decides, with the backup, from the messages already printed."""
        stack = self.stack
        stack.signals.defer()
        if self.phase == PRE_MIGRATION:
            self._put_the_old_version_back()
            return
        for path in self.backup.partial:
            with contextlib.suppress(OSError):
                path.unlink()
        self.backup.resume_hindsight()
        stack.compose("stop", *WRITERS)
        self.backup.paused = []

    def _put_the_old_version_back(self) -> None:
        stack = self.stack
        moved = bool(self.before) and stack.git_read("rev-parse", "HEAD") != self.before
        # --keep fails rather than touch local changes; the message says how to move the code.
        if moved and stack.program(["git", "-C", str(stack.repo), "reset", "--keep", self.before]) != 0:
            stack.errf("up_class_stuck", stack.repo, self.before)
        if self.built and self.prev_image and not stack.docker("tag", self.prev_image, self.cur_image):
            self.retag_failed = True
            stack.errf("up_retag_failed", self.cur_image, stack.log, self.prev_tag)
        stopped = len(self.backup.paused)
        self.backup.abort()
        if self.backup.paused:
            stack.errf("up_old_failed", stack.log)
        elif self.retag_failed:
            stack.errf("up_old_not_running", self.cur_image, self.prev_tag, self.prev_tag, self.cur_image)
        elif stopped > 0:
            stack.sayf("up_old_running", self.prev_tag or self.cur_image)

    def stays_stopped(self, after: str, branch: str) -> Stop:
        """The messages after a failure from the migration on: the writers stay stopped (``abort`` does it), the backup
        is named, the way back for the code is given, and nothing is restored."""
        stack, backup = self.stack, self.backup
        stack.errf(
            "up_stay_stopped",
            " ".join(WRITERS),
            backup.db or "",
            backup.mem or "",
            stack.backups,
            backup.stamp,
            self.prev_tag or "none",
        )
        stack.errf("up_rollback", self.before, after, stack.repo, self.before, stack.backups, stack.repo, branch)
        return Stop(1)

    # -- the steps ---------------------------------------------------------------------------------------------

    def migration_class_ok(self) -> bool:
        """The migration class of an update, as deploy/selfhost/update.sh decides it from the image label: the new code
        may only bring migrations the old code can still run against (expand-only) unless --allow-breaking-migration is
        given. This package builds its image from the checkout and has no label, so the checker compares the migrations
        since the commit that was installed."""
        stack = self.stack
        script = stack.repo / "tools" / "check-release-migration-class.py"
        release_class = "breaking" if self.allow_breaking else "expand"
        status = stack.program(
            [sys.executable, str(script), "--release-class", release_class, "--installed", self.before]
        )
        if status == 0:
            return True
        stack.tail_log()
        stack.errf(migration_refusal(status), stack.log)
        return False

    def _fail(self, key: str, after: str, branch: str, *, tail: bool) -> Stop:
        """A step after the migration began failed: say so, and where the backups are."""
        stack = self.stack
        stack.errf(key, stack.log, stack.backups)
        if tail:
            stack.tail_log()
        return self.stays_stopped(after, branch)

    def _restart_gateway_if_changed(self) -> bool:
        """The gateway configuration is a mounted file that compose does not watch: restart the gateway when it
        changed."""
        stack = self.stack
        current, applied = stack.gen / "gateway.haproxy.cfg", stack.gen / ".gateway.applied"
        if applied.is_file() and applied.read_bytes() == current.read_bytes():
            return True
        return stack.compose("restart", "gateway")

    def run(self) -> None:
        stack = self.stack
        self.save_previous_image()
        before = stack.git_read("rev-parse", "HEAD")
        if before is None:
            raise Stop(1)
        self.before = before
        branch = stack.git_read("rev-parse", "--abbrev-ref", "HEAD") or "HEAD"
        if stack.program(["git", "-C", str(stack.repo), "pull", "--ff-only"]) != 0:
            stack.errf("up_pull_fail", stack.log)
            raise Stop(1)
        after = stack.git_read("rev-parse", "HEAD")
        if after is None:
            raise Stop(1)
        # A refusal ends the command; the cleanup puts the code back on ``before``.
        if before != after and not self.migration_class_ok():
            raise Stop(1)
        if before == after:
            stack.sayf("up_same", after[:10])
        else:
            stack.sayf("up_changed", before[:10], after[:10])
        secretfiles.write_rooms_env(stack.secrets, workenv.env_value(stack.work_env, secretfiles.ROOMS_NAME))
        stackfiles.render_generated(stack, self.allow)
        stack.say("up_building")
        if not stack.compose("pull", "--ignore-buildable", "--quiet"):
            stack.errf("up_offline")
        self.built = True
        if not stack.compose("build", "api"):
            stack.errf("up_build_fail", stack.log)
            stack.tail_log()
            raise Stop(1)
        # Only now are the writers stopped, and they stay stopped until the new version is up and ready: nothing writes
        # between the backup and the migration. The running containers keep the previous image until they are recreated.
        self.backup.take()
        # The image built above migrates while nothing writes. yoyo is idempotent, so the start below, which reruns the
        # one-shot migrate service before the api starts, finds nothing left to do.
        self.phase = MIGRATING
        if not stack.compose("run", "--rm", "-T", "--no-deps", "migrate"):
            stack.errf("up_migrate_fail", stack.log, stack.backups)
            stack.tail_log()
            raise self.stays_stopped(after, branch)
        # The api alone first, because the readiness check runs in it; the memory worker and the automation worker start
        # only after it has passed (they are recreated by this, their image is new), and then the whole stack is
        # checked again.
        if not stack.compose("up", "-d", "--wait", "--wait-timeout", START_TIMEOUT, "--force-recreate", "api"):
            raise self._fail("up_restart_fail", after, branch, tail=True)
        if not wait_ready(stack):
            raise self._fail("up_ready_fail", after, branch, tail=False)
        if not stack.compose("up", "-d", "--wait", "--wait-timeout", START_TIMEOUT):
            raise self._fail("up_restart_fail", after, branch, tail=True)
        if not self._restart_gateway_if_changed():
            stack.errf("gw_fail", stack.log)
            raise self.stays_stopped(after, branch)
        if not wait_ready(stack):
            raise self._fail("up_ready_fail", after, branch, tail=False)

    def finish(self) -> None:
        """The new version is up and ready: prune the old backups and write what the interface shows."""
        stack = self.stack
        self.backup.prune()
        shutil.copyfile(stack.gen / "gateway.haproxy.cfg", stack.gen / ".gateway.applied")
        stackfiles.write_build_info(stack, self.before, updated=True)
        desktopsetup.desktop_setup(stack)
        stack.sayf("up_done", stack.gen / stackfiles.BUILD_INFO)


def run_update(stack: Stack, allow_breaking: bool, allow: list[tuple[str, int]]) -> int:
    """Returns the exit status; runs under the lock."""
    return worklock.run_locked(stack, "update", lambda: _update(stack, allow_breaking, allow))


def _update(stack: Stack, allow_breaking: bool, allow: list[tuple[str, int]]) -> int:
    update = Update(stack, allow_breaking, allow)
    finished = False
    code = 0
    with stack.caught_signals():
        try:
            update.run()
            update.backup.paused = []
            finished = True
            update.finish()
        except Stop as stop:
            code = stop.code
        finally:
            if not finished:
                update.abort()
                code = stack.signals.settle(code)
    return code
