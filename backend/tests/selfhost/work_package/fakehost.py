"""A stand-in for ``workctl.drillhost.Host`` that starts nothing: the drill's decisions and the
order of its calls are tested without docker.

Every program the drill runs is recorded as one line (its arguments joined by blanks) and answered
by ``answer(call, stdin, env)``: ``None`` is a success that printed nothing, text or bytes a success
that printed that, an int an exit status, a ``Done`` itself. ``Healthy`` is an answer that behaves
like a working stack (a marker row, a marker file in the Hindsight volume, a schema version,
encrypted backups) and can be told to misbehave."""

import base64
import io
import re
import tarfile
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path
from typing import Any

from tools.workctl.drillhost import Done, Host

HEADER = b"SIDEKICK-SNAPSHOT-1\n"
KEY_VARIABLE = "SIDEKICK_BACKUP_ENCRYPTION_KEY"
KEY_FILE_VARIABLE = "SIDEKICK_WORK_BACKUP_KEY_FILE"


def tar_with(name: str, content: str) -> bytes:
    buffer = io.BytesIO()
    with tarfile.open(fileobj=buffer, mode="w:gz") as archive:
        data = content.encode()
        info = tarfile.TarInfo(name)
        info.size = len(data)
        archive.addfile(info, io.BytesIO(data))
    return buffer.getvalue()


def file_of(archive: bytes) -> str:
    with tarfile.open(fileobj=io.BytesIO(archive), mode="r:gz") as opened:
        member = opened.getmembers()[0]
        extracted = opened.extractfile(member)
        assert extracted is not None
        return extracted.read().decode()


def _group(pattern: str, text: str) -> str:
    found = re.search(pattern, text)
    assert found is not None, (pattern, text)
    return found.group(1)


class FakeHost(Host):
    def __init__(
        self, answer: Callable[[str, bytes | None, Mapping[str, str]], Any] | None = None
    ) -> None:
        self.calls: list[str] = []
        self.answer = answer or (lambda _call, _stdin, _env: None)
        self.ports = iter(range(30001, 30100))
        self.now = 0.0
        self.slept = 0.0
        self.open_ports: set[int] = set()

    def run(
        self,
        argv: Sequence[str],
        *,
        env: Mapping[str, str],
        stdin: bytes | None = None,
        cwd: Path | None = None,
        merge: bool = False,
    ) -> Done:
        call = " ".join(argv)
        self.calls.append(call)
        reply = self.answer(call, stdin, {**env, "CWD": str(cwd or "")})
        if isinstance(reply, Done):
            return reply
        if reply is None:
            return Done(0)
        if isinstance(reply, int) and not isinstance(reply, bool):
            return Done(reply, b"", b"failed\n")
        return Done(0, reply if isinstance(reply, bytes) else str(reply).encode())

    def free_port(self, reserved: Sequence[int], used: Sequence[int]) -> int | None:
        return next(self.ports, None)

    def port_open(self, port: int) -> bool:
        return True

    def sleep(self, seconds: float) -> None:
        self.slept += seconds

    def clock(self) -> float:
        self.now += 1
        return self.now


class Healthy:
    """Answers the calls of both scenarios the way a working stack does.

    ``faults`` are ways to misbehave: ``lose-marker`` (the row is gone after the first write),
    ``no-schema-move``, ``wrong-key-accepted``, ``lose-hindsight`` (the marker file is gone after a
    restore) and ``no-digest``."""

    def __init__(self, *faults: str) -> None:
        self.faults = set(faults)
        self.marker: str | None = None
        self.hindsight: str | None = None
        self.saved_marker = ""
        self.saved_hindsight = ""
        self.schema = 10
        self.pushed = 0
        self.work_image = ""
        self.lost = False

    def __call__(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        for handler in (self.database, self.volume, self.crypto, self.scripts, self.images):
            reply = handler(call, stdin, env)
            if reply is not NotImplemented:
                return reply
        return None

    # -- docker, compose, psql ---

    def database(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        found = re.search(r"VALUES \('([^']+)'\)", call)
        if found:
            self.marker = None if "lose-marker" in self.faults else found.group(1)
            self.saved_marker = found.group(1)
            return b""
        if "from public.drill_marker" in call:
            if "lose-marker" in self.faults and self.marker is None:
                return b""
            return self.marker or Done(1, b"", b"relation does not exist\n")
        if "count(*) from _yoyo_migration" in call:
            return str(self.schema)
        if "migration_id from _yoyo_migration" in call:
            return f"{self.schema:04d}_head"
        if "create-user" in call:
            return "created\n00000000-0000-4000-8000-000000000001\n"
        if "sidekick.users" in call:
            return "1"
        if "pg_dump" in call:
            return b"dump:" + self.saved_marker.encode()
        if "pg_restore -l" in call:
            return b"drill_marker\n"
        if "pg_restore" in call:
            assert stdin is not None
            self.marker = stdin.decode().removeprefix("dump:")
            return b""
        return NotImplemented

    def volume(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        if "docker ps -a" in call or "docker ps -q" in call:
            return "hindsight-image" if "service=hindsight" in call else "container-1"
        if "volume ls" in call:
            return "p_hindsight_pg0" if "hindsight_pg0" in call else ""
        if "down -v" in call:
            self.marker = self.hindsight = None
            return b""
        if "printf '%s'" in call:
            self.hindsight = _group(r"printf '%s' '([^']+)'", call)
            return b""
        if "--entrypoint cat" in call:
            if self.hindsight:
                return self.hindsight
            return b"" if self.lost else Done(1, b"", b"No such file\n")
        if "--entrypoint tar" in call:
            self.saved_hindsight = self.hindsight or ""
            return tar_with("drill-marker.txt", self.hindsight or "")
        if "find /dst" in call:
            assert stdin is not None
            self.lost = "lose-hindsight" in self.faults
            self.hindsight = None if self.lost else file_of(stdin)
            return b""
        return NotImplemented

    def crypto(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        if "snapshot_crypto" not in call and "python -I -c" not in call:
            return NotImplemented
        assert stdin is not None
        if call.endswith(" encrypt"):
            return HEADER + base64.b64encode(stdin)
        if KEY_VARIABLE in env and "wrong-key-accepted" not in self.faults:
            return Done(1, b"", b"wrong key\n")
        return base64.b64decode(stdin.removeprefix(HEADER))

    # -- update.sh and work.sh ---

    def scripts(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        if "update.sh" in call:
            directory = Path(_group(r"-f (\S+)/compose\.yaml", call))
            if "--decrypt-snapshot" in call:
                return b"dump"
            image = call.split("--image ")[1].split()[0]
            state = directory / "update-state"
            (state / "snapshots").mkdir(parents=True, exist_ok=True)
            (state / "snapshots" / "sidekick-pre-1.dump.enc").write_bytes(HEADER + b"dump")
            (state / "journal.log").write_text("2026-01-01T00:00:00Z DONE\n")
            (directory / "release.env").write_text(f"SIDEKICK_API_IMAGE={image}\n")
            self.schema += 0 if "no-schema-move" in self.faults else 2
            return b""
        if "tools/work.sh" not in call:
            return NotImplemented
        repo = Path(env["CWD"])
        words = call.split()
        command = words[2]
        if command == "backup":
            backups = repo / "deploy" / "work" / "backups"
            backups.mkdir(parents=True, exist_ok=True)
            (repo / "deploy" / "work" / "secrets").mkdir(parents=True, exist_ok=True)
            (repo / "deploy" / "work" / "secrets" / "backup.key").write_text("key\n")
            self.saved_hindsight = self.hindsight or ""
            (backups / "sidekick-20260101-000000.sql.enc").write_bytes(HEADER + b"dump")
            (backups / "hindsight-20260101-000000.tar.gz.enc").write_bytes(HEADER + b"archive")
            return b""
        if command == "start":
            image = _group(
                r"SIDEKICK_WORK_API_IMAGE=(\S+)",
                (repo / "deploy" / "work" / "work.env").read_text(),
            )
            if self.work_image and image != self.work_image and "no-schema-move" not in self.faults:
                self.schema += 2
            self.work_image = image
        if command == "restore":
            wrong = KEY_FILE_VARIABLE in env and "wrong-key-accepted" not in self.faults
            if wrong:
                return Done(1, b"", b"cannot decrypt\n")
            self.marker = self.saved_marker
            self.lost = "lose-hindsight" in self.faults
            self.hindsight = None if self.lost else self.saved_hindsight
        return b""

    def images(self, call: str, stdin: bytes | None, env: Mapping[str, str]) -> Any:
        if " build " in call:
            return b""
        if " push " in call:
            if "no-digest" in self.faults:
                return b"pushed without a digest\n"
            self.pushed += 1
            return f"digest: sha256:{str(self.pushed) * 64} size: 1\n".encode()
        return NotImplemented
