"""The disposable-container drill: install -> update -> backup -> destroy -> restore, for the self-hosted stack
(``deploy/selfhost``: ``update.sh`` and its encrypted snapshot) and for the work package (``tools/work.sh``: encrypted
database and Hindsight backups with their own key), each in its own throw-away compose project. ``tools/drill.sh`` is
the shell around this module; the scenarios are ``drillselfhost`` and ``drillwork``.

Safety, by construction:

* every compose project is named ``sk-drill-<random>-<scenario>``; the run refuses (exit 2) any other name, and the
  cleanup runs ``docker compose -p <that project> down -v --remove-orphans`` for those projects only (plus the leftover
  volumes that carry the label of one of them) and removes the images ``--local-images`` built (by their exact
  references), then removes the temp dir;
* all state (env files, secrets, backups, keys, a copy of the deploy files) lives in one temp dir; the real deploy
  directories, env files and secrets of the repository are never read, written or copied (env files and secrets
  directories are left out of the copy);
* published ports are random, bound to 127.0.0.1, and never one of the reserved ports (``drillpolicy.RESERVED_PORTS``;
  ``SIDEKICK_RESERVED_PORTS``, comma-separated, adds more and never removes any);
* the self-hosted stack runs with its ``memory`` profile, so the drill covers the Hindsight volume the way the guide
  archives and restores it;
* the scenarios run the real ``update.sh`` and the real ``tools/work.sh`` (copied into the temp dir).

``DRILL_FAKE_FAIL`` (dry run only) makes the fake docker misbehave to prove the drill notices: a comma list of
``lose-marker``, ``no-schema-move``, ``wrong-key-accepted``, ``lose-hindsight``. ``DRILL_FAKE_LOG`` names the file the
fake docker logs every call to (default: inside the temp dir, so gone after the run). ``DRILL_KEEP_TEMP=1`` keeps the
temp dir (the compose projects are still removed).

Every step prints its duration; the table of durations follows the summary. In GitHub Actions a failed step also
becomes an error annotation and the table goes to the job summary.

Exit status: 0 all steps passed, 1 a step failed, 2 usage error or a refused input.
"""

from __future__ import annotations

import contextlib
import os
import shlex
import shutil
import signal
import sys
import tempfile
import threading
from collections.abc import Callable, Generator, Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from types import FrameType
from typing import Protocol

from . import drillimages, drillpolicy, drilltimings
from .drillhost import Host
from .drillpolicy import Refused
from .drillselfhost import Selfhost
from .drillsteps import Run, Step, StepFailed, rand_hex8
from .drillwork import Work

REPO = Path(__file__).resolve().parents[2]
USAGE_EXIT, FAILED_EXIT = 2, 1
SIGNAL_EXIT = {signal.SIGINT: 130, signal.SIGTERM: 143}
LOG_TAIL_LINES = 15
SCENARIOS = ("selfhost", "work", "all")
VALUE_OPTIONS = ("--from-image", "--to-image", "--cert-identity", "--log", "--project")
USAGE = """\
Disposable-container drill: install -> update -> backup -> destroy -> restore, for the self-hosted stack
(deploy/selfhost: update.sh, its encrypted snapshot) and for the work package (tools/work.sh: encrypted database
and Hindsight backups with their own key), each in its own throw-away compose project.

  bash tools/drill.sh selfhost|work|all [--from-image REF] [--to-image REF] [--cert-identity ID]
                                         [--local-images] [--allow-same-schema] [--log FILE] [--dry-run]

  --from-image REF   the previously released api image to install first (env DRILL_FROM_IMAGE)
  --to-image REF     the image to update to (env DRILL_TO_IMAGE); both must be REGISTRY/REPO@sha256:<64 hex>
  --cert-identity ID signer identity update.sh must find in the cosign signature (env DRILL_CERT_IDENTITY);
                     needed for selfhost, which verifies the real signature (cosign must be installed)
  --local-images     no released images: build the api image twice from this checkout (versions X.Y.Z and X.Y.Z+1),
                     push both to a throw-away registry on 127.0.0.1 to get real digests, and drill with them.
                     cosign is a stand-in that only checks the shape of the call, so the signature itself is NOT
                     verified in this mode (that needs released images); implies --allow-same-schema. Needs
                     docker, python3 and the registry image (pulled when missing). Not combinable with --dry-run
                     or with --from-image/--to-image.
  --allow-same-schema  accept an update that does not move the schema version (a patch release without migrations)
  --log FILE         where the step log goes (default: a new file in $TMPDIR; its path is printed at the end)
  --dry-run          a fake docker and cosign in a temp bin dir; nothing real is started (same as DRILL_FAKE_DOCKER=1)
  --project NAME     base name of the compose projects; MUST start with sk-drill- (anything else: exit 2, nothing runs)
"""
# Nothing from the caller's shell may steer the stacks of the drill.
UNSET = (
    "SIDEKICK_API_IMAGE",
    "SIDEKICK_API_IMAGE_PREVIOUS",
    "SIDEKICK_WORK_API_IMAGE",
    "SIDEKICK_WORK_PROJECT",
    "SIDEKICK_WORK_BACKUP_KEY_FILE",
    "SIDEKICK_BACKUP_ENCRYPTION_KEY",
    "SIDEKICK_RELEASE_CERT_IDENTITY",
    "COMPOSE_FILE",
    "COMPOSE_PROJECT_NAME",
    "COMPOSE_PROFILES",
)
FAKE_ENV = {
    "SIDEKICK_UPDATE_POLL_SECONDS": "0.1",
    "SIDEKICK_UPDATE_HEALTH_TIMEOUT": "60",
    "SIDEKICK_WORK_READY_POLL": "0.1",
}


class Usage(Refused):
    """The arguments are not understood; the message is the usage text."""


@dataclass(frozen=True)
class Options:
    scenario: str
    dry: bool
    from_image: str
    to_image: str
    identity: str
    allow_same_schema: bool
    local_images: bool
    base_project: str
    log: Path | None


class Scenario(Protocol):
    name: str
    project: str

    def steps(self) -> list[tuple[str, Callable[[Step], None]]]: ...


def parse_options(argv: Sequence[str], environ: Mapping[str, str]) -> Options:
    """The options of a run, with every refusal (``Usage`` for an argument that is not understood) raised as
    ``Refused``; nothing has been started when it is."""
    args = list(argv)
    if not args or args[0] not in SCENARIOS:
        raise Usage(USAGE)
    scenario = args.pop(0)
    dry = environ.get("DRILL_FAKE_DOCKER") == "1"
    from_image, to_image = environ.get("DRILL_FROM_IMAGE", ""), environ.get("DRILL_TO_IMAGE", "")
    identity = environ.get("DRILL_CERT_IDENTITY", "")
    allow_same_schema = local_images = False
    given: dict[str, str] = {}
    while args:
        option = args.pop(0)
        if option == "--dry-run":
            dry = True
        elif option == "--allow-same-schema":
            allow_same_schema = True
        elif option == "--local-images":
            local_images = True
        elif option in VALUE_OPTIONS and args:
            given[option] = args.pop(0)
        else:
            raise Usage(USAGE)
    from_image = given.get("--from-image", from_image)
    to_image = given.get("--to-image", to_image)
    identity = given.get("--cert-identity", identity)
    log = Path(given["--log"]) if given.get("--log") else None
    base_project = drillpolicy.require_project(given.get("--project") or f"{drillpolicy.PROJECT_PREFIX}{rand_hex8()}")
    for suffix in ("sh", "wk", "reg"):
        drillpolicy.require_project(f"{base_project}-{suffix}")
    if local_images:
        if dry or from_image or to_image:
            raise Refused(
                "drill: --local-images builds and runs real images; it cannot be combined with --dry-run, "
                "--from-image or --to-image"
            )
        identity = identity or "drill@example.invalid"
        allow_same_schema = True  # both images come from the same checkout: the schema cannot move
        from_image = to_image = "local"  # placeholders until the images are built
    if dry:
        from_image = from_image or f"registry.example/sidekick@sha256:{'a' * 64}"
        to_image = to_image or f"registry.example/sidekick@sha256:{'b' * 64}"
        identity = identity or "drill@example.invalid"
    if not local_images:
        drillpolicy.check_image_pair(from_image, to_image)
    if scenario != "work" and not identity:
        raise Refused(
            "drill: selfhost needs --cert-identity (or DRILL_CERT_IDENTITY): update.sh verifies the real signature"
        )
    return Options(scenario, dry, from_image, to_image, identity, allow_same_schema, local_images, base_project, log)


class Drill:
    """One run: the temp dir and log, the steps with their timings, the summary and the cleanup."""

    def __init__(
        self,
        options: Options,
        *,
        environ: Mapping[str, str],
        reserved: Sequence[int] = drillpolicy.RESERVED_PORTS,
        host: Host | None = None,
        repo: Path = REPO,
    ) -> None:
        self.options = options
        self.environ = dict(environ)
        self.reserved = list(reserved)
        self.host = host or Host()
        self.repo = repo
        self.base = options.base_project
        self.projects: list[str] = []
        self.local_refs: list[str] = []
        self.used_ports: list[int] = []
        self.timings: list[drilltimings.Timing] = []
        self.step_count = 0
        self.passed: list[str] = []
        self.failed: list[str] = []
        self.tmp = Path()
        self.log = Path()
        self.shared: Run

    # -- output -----------------------------------------------------------------------------------------------

    def say(self, text: str) -> None:
        print(text, flush=True)
        self.append_log(text + "\n")

    def append_log(self, text: str | bytes) -> None:
        data = text.encode("utf-8") if isinstance(text, str) else text
        with self.log.open("ab") as handle:
            handle.write(data)

    # -- the run ------------------------------------------------------------------------------------------------

    def run(self) -> int:
        code = FAILED_EXIT
        directory = self.environ.get("TMPDIR") or "/tmp"  # noqa: S108 - where ``mktemp`` looks without TMPDIR
        self.tmp = Path(tempfile.mkdtemp(prefix="sk-drill.", dir=directory))
        if self.options.log is None:
            handle, name = tempfile.mkstemp(prefix="sk-drill-log.", dir=directory)
            os.close(handle)
            self.log = Path(name)
        else:
            self.log = self.options.log
            self.log.write_bytes(b"")
        env = {name: value for name, value in self.environ.items() if name not in UNSET}
        self.shared = Run(
            self.repo,
            self.tmp,
            self.host,
            env,
            self.options.dry,
            self.options.from_image,
            self.options.to_image,
            self.options.identity,
            self.options.allow_same_schema,
        )
        try:
            with self.caught_signals():
                code = self.execute()
        except Refused as refusal:
            print(refusal, file=sys.stderr)
            code = USAGE_EXIT
        except SystemExit as stop:
            code = stop.code if isinstance(stop.code, int) else FAILED_EXIT
        finally:
            self.cleanup()
        return code

    @contextlib.contextmanager
    def caught_signals(self) -> Generator[None]:
        """An interrupt or a terminate ends the run with the shell's status (130, 143); the cleanup still runs."""
        if threading.current_thread() is not threading.main_thread():
            yield
            return

        def leave(number: int, _frame: FrameType | None) -> None:
            raise SystemExit(SIGNAL_EXIT[signal.Signals(number)])

        previous = {number: signal.signal(number, leave) for number in SIGNAL_EXIT}
        try:
            yield
        finally:
            for number, handler in previous.items():
                signal.signal(number, handler)

    def execute(self) -> int:
        options = self.options
        if options.dry:
            self.write_fake_tools()
        else:
            self.preflight()
        if options.dry:
            self.say("drill: DRY RUN with a fake docker; nothing real is started")
        base = self.base
        planned = {"selfhost": [f"{base}-sh"], "work": [f"{base}-wk"], "all": [f"{base}-sh", f"{base}-wk"]}[
            options.scenario
        ]
        if options.local_images:
            planned = [f"{base}-reg", *planned]
        self.say(
            f"drill: projects {' '.join(planned)}; reserved ports: {' '.join(str(port) for port in self.reserved)}"
        )
        if options.local_images and not self.build_local_images():
            self.report_timings()
            self.say("SUMMARY: FAIL (the local images could not be built)")
            return FAILED_EXIT
        for name in ("selfhost", "work") if options.scenario == "all" else (options.scenario,):
            self.run_scenario(name)
        if not self.failed:
            self.say(f"SUMMARY: PASS ({self.step_count} steps; scenarios: {' '.join(self.passed)})")
            self.report_timings()
            return 0
        self.say(
            f"SUMMARY: FAIL (failed scenarios: {' '.join(self.failed)}; passed: {' '.join(self.passed) or 'none'})"
        )
        self.report_timings()
        return FAILED_EXIT

    # -- the tools of the run ---------------------------------------------------------------------------------

    def put_in_front(self, name: str, text: str) -> None:
        shim = self.tmp / "bin" / name
        shim.parent.mkdir(exist_ok=True)
        shim.write_text(text, encoding="utf-8")
        shim.chmod(0o755)
        env = self.shared.env
        env["PATH"] = f"{self.tmp / 'bin'}{os.pathsep}{env.get('PATH', '')}"

    def write_fake_tools(self) -> None:
        """A fake docker and cosign (``--dry-run``): the fake keeps a small state file and logs every call. It refuses
        (exit 99) any project, volume or bind that is not an ``sk-drill-`` one."""
        fake = self.tmp / "fake"
        fake.mkdir(parents=True, exist_ok=True)
        env = self.shared.env
        env["DRILL_FAKE_STATE"] = str(fake / "state.json")
        env["DRILL_FAKE_LOG"] = env.get("DRILL_FAKE_LOG") or str(fake / "calls.log")
        env["DRILL_FAKE_FROM"], env["DRILL_FAKE_TO"] = self.options.from_image, self.options.to_image
        Path(env["DRILL_FAKE_LOG"]).write_bytes(b"")
        env.update(FAKE_ENV)
        # The fake docker is tools/drill_fake_docker.py (the host's python3); the shim only starts it.
        python = shutil.which("python3") or sys.executable
        fake_docker = self.repo / "tools" / "drill_fake_docker.py"
        self.put_in_front("docker", f'#!/bin/sh\nexec {shlex.quote(python)} -I {shlex.quote(str(fake_docker))} "$@"\n')
        self.put_in_front("cosign", "#!/bin/sh\nexit 0\n")

    def preflight(self) -> None:
        path = self.shared.env.get("PATH")
        scenario = self.options.scenario
        needed = ["docker", "python3", "sed", "awk"]
        if scenario != "work" and not self.options.local_images:
            needed.append("cosign")
        if scenario != "selfhost":
            needed.append("openssl")
        for tool in needed:
            if shutil.which(tool, path=path) is None:
                reason = {
                    "cosign": "cosign is required (update.sh verifies the signature, fail closed)",
                    "openssl": "openssl is required (tools/work.sh)",
                }.get(tool, f"{tool} is required")
                raise Refused(f"drill: {reason}")
        if self.host.run(["docker", "compose", "version"], env=self.shared.env, merge=True).rc != 0:
            raise Refused("drill: docker compose v2 is required")

    def pick_port(self) -> int:
        port = self.host.free_port(self.reserved, self.used_ports)
        if port is None:
            print("drill: no free port found", file=sys.stderr)
            raise SystemExit(FAILED_EXIT)
        self.used_ports.append(port)
        return port

    def build_local_images(self) -> bool:
        """The images ``--local-images`` builds, behind a registry of their own; the stand-in cosign goes in front of
        the real one."""
        self.say(
            "drill: --local-images: the signature is NOT verified (cosign is a stand-in); "
            "released images are needed for that"
        )
        self.put_in_front("cosign", drillimages.cosign_standin(self.options.identity))
        registry = f"127.0.0.1:{self.pick_port()}"
        project = f"{self.base}-reg"
        self.projects.append(project)

        def build(step: Step) -> None:
            drillimages.build_images(step, self.shared, project=project, address=registry, refs=self.local_refs)

        if not self.step("setup", "local-images", build):
            return False
        self.shared.from_image, self.shared.to_image = self.shared.kv["from_image"], self.shared.kv["to_image"]
        return True

    # -- the steps ------------------------------------------------------------------------------------------------

    def step(self, scenario: str, name: str, function: Callable[[Step], None]) -> bool:
        """Run one step with its output kept for the log; True when it passed."""
        self.step_count += 1
        step = Step(self.shared)
        started = self.host.clock()
        code = 0
        try:
            function(step)
        except StepFailed as failure:
            step.note(str(failure))
            code = failure.code
        except Exception as error:  # whatever goes wrong inside a step fails that step, as in a shell
            step.note(f"{type(error).__name__}: {error}")
            code = FAILED_EXIT
        took = int(self.host.clock() - started)
        self.append_log(f"--- {scenario}/{name} (exit {code}, {took}s)\n")
        self.append_log(bytes(step.output))
        if code == 0:
            self.timings.append(drilltimings.Timing("PASS", f"{scenario}/{name}", took))
            self.say(f"PASS {scenario}/{name} ({took}s)")
            return True
        self.timings.append(drilltimings.Timing("FAIL", f"{scenario}/{name}", took))
        self.say(f"FAIL {scenario}/{name} (exit {code}, {took}s)")
        for line in bytes(step.output).decode("utf-8", errors="replace").splitlines()[-LOG_TAIL_LINES:]:
            print(f"    {line}", flush=True)
        # A failed step names itself in the Actions run, so the log does not have to be opened to see which one broke.
        if self.environ.get("GITHUB_ACTIONS") == "true":
            print(
                f"::error title=drill {scenario}/{name} failed::exit {code} after {took}s, see the drill log artifact",
                flush=True,
            )
        return False

    def run_scenario(self, name: str) -> None:
        port = self.pick_port()
        env = self.shared.env
        if self.options.dry:
            Path(env["DRILL_FAKE_STATE"]).unlink(missing_ok=True)
        scenario: Scenario
        if name == "selfhost":
            scenario = Selfhost(self.shared, f"{self.base}-sh", port)
            self.say(f"selfhost: project {scenario.project}, api on 127.0.0.1:{port}")
        else:
            scenario = Work(self.shared, f"{self.base}-wk", port)
            self.say(f"work: project {scenario.project}, gateway on 127.0.0.1:{port}")
        self.projects.append(scenario.project)
        env["COMPOSE_PROJECT_NAME"] = scenario.project
        # The steps in order, stopping at the first failure.
        passed = all(self.step(name, step_name, function) for step_name, function in scenario.steps())
        (self.passed if passed else self.failed).append(name)

    def report_timings(self) -> None:
        """The durations, as text and (in GitHub Actions) as a table in the job summary."""
        if not self.timings:
            return
        self.say("\n".join(drilltimings.text_table(self.timings)))
        summary = self.environ.get("GITHUB_STEP_SUMMARY")
        if summary:
            with Path(summary).open("a", encoding="utf-8") as handle:
                handle.write("\n".join(drilltimings.markdown_table(self.timings)) + "\n")

    # -- the cleanup ------------------------------------------------------------------------------------------------

    def docker(self, *args: str) -> str:
        """A docker call of the cleanup: its output goes to the log, its text is returned."""
        done = self.host.run(["docker", *args], env=self.shared.env, merge=True)
        self.append_log(done.out)
        return done.out.decode("utf-8", errors="replace")

    def cleanup(self) -> None:
        """Only the projects of this run; a name that is not ``sk-drill-*`` is skipped, never passed on to docker."""
        for project in self.projects:
            if not drillpolicy.valid_project(project):
                continue
            self.docker("compose", "-p", project, "down", "-v", "--remove-orphans")
            # Volumes of this project that `down` did not reach (for example one created ahead of the first `up`).
            listed = self.host.run(
                ["docker", "volume", "ls", "-q", "--filter", f"label=com.docker.compose.project={project}"],
                env=self.shared.env,
            )
            for volume in listed.out.decode("utf-8", errors="replace").split():
                if volume.startswith(f"{project}_"):
                    self.docker("volume", "rm", volume)
        # The images --local-images built, by their exact references, never by a pattern.
        for reference in self.local_refs:
            if drillimages.is_local_reference(reference):
                self.docker("image", "rm", reference)
        if self.environ.get("DRILL_KEEP_TEMP") == "1":
            print(f"drill: temp dir kept: {self.tmp}", file=sys.stderr)
        elif self.tmp.is_dir() and self.tmp.name.startswith("sk-drill."):
            shutil.rmtree(self.tmp, ignore_errors=True)
        print(f"drill: log: {self.log}", file=sys.stderr)


def main(argv: Sequence[str], environ: Mapping[str, str] | None = None) -> int:
    environ = os.environ if environ is None else environ
    try:
        extra = environ.get("SIDEKICK_RESERVED_PORTS", "")
        reserved = [*drillpolicy.RESERVED_PORTS, *(drillpolicy.extra_reserved_ports(extra) if extra else [])]
        options = parse_options(argv, environ)
    except Refused as refusal:
        print(refusal, file=sys.stderr, end="" if isinstance(refusal, Usage) else "\n")
        return USAGE_EXIT
    return Drill(options, environ=environ, reserved=reserved).run()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
