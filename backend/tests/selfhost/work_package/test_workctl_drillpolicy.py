"""The other checks of tools/drill.sh (workctl drill-*), as functions and as commands."""

import io
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from tools.workctl import cli, drillpolicy

from tests.selfhost.work_package.support import REPO_ROOT

DIGEST = "sha256:" + "a" * 64
FROM = "registry.example/sidekick@" + DIGEST
TO = "registry.example/sidekick@sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("value", "ports"),
    [
        ("9000", [9000]),
        (" 030000, 9000", [30000, 9000]),
        ("1,65535", [1, 65535]),
        ("9000,,9001, ", [9000, 9001]),
        (" , ", []),
    ],
)
def test_extra_reserved_ports_are_normalised_to_decimal(value: str, ports: list[int]) -> None:
    assert drillpolicy.extra_reserved_ports(value) == ports


@pytest.mark.parametrize(
    "value", ["abc", "70000", "0", "000", "9000\n9001", "55436,x", "9000;1", "-1", "9 000x"]
)
def test_a_malformed_reserved_ports_value_is_refused(value: str) -> None:
    with pytest.raises(
        drillpolicy.Refused, match="SIDEKICK_RESERVED_PORTS must be comma-separated"
    ):
        drillpolicy.extra_reserved_ports(value)


def test_the_image_pair_must_be_given_pinned_and_different() -> None:
    drillpolicy.check_image_pair(FROM, TO)
    with pytest.raises(drillpolicy.Refused, match="are required, or --local-images"):
        drillpolicy.check_image_pair("", TO)
    with pytest.raises(drillpolicy.Refused, match="are required"):
        drillpolicy.check_image_pair(FROM, "")
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair("registry.example/sidekick:1.0", TO)
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair(FROM, "registry.example/sidekick@sha256:abc")
    with pytest.raises(drillpolicy.Refused, match="must differ"):
        drillpolicy.check_image_pair(FROM, FROM)


@pytest.mark.parametrize(
    "image", ["Registry/x@" + DIGEST, "x@" + DIGEST + "\n", "@" + DIGEST, "x y@" + DIGEST]
)
def test_a_digest_pin_has_no_uppercase_blank_or_trailing_newline(image: str) -> None:
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair(image, TO)


def test_a_picked_port_is_never_reserved_used_or_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = iter([20000, 20001, 20002, 20003])
    asked: list[tuple[int, int]] = []

    def randint(low: int, high: int) -> int:
        asked.append((low, high))
        return next(candidates)

    monkeypatch.setattr(drillpolicy.random, "randint", randint)
    port = drillpolicy.pick_port([20000], [20001], lambda candidate: candidate == 20002)
    assert port == 20003
    assert asked == [(20000, 39999)] * 4


def test_a_listening_port_is_skipped_and_the_search_gives_up_after_50_tries() -> None:
    tried: list[int] = []

    def busy(port: int) -> bool:
        tried.append(port)
        return True

    assert drillpolicy.pick_port([], [], busy) is None
    assert len(tried) == drillpolicy.PICK_ATTEMPTS


def test_a_port_that_something_listens_on_is_detected() -> None:
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        busy = server.getsockname()[1]
        assert drillpolicy.listening(busy)
    assert not drillpolicy.listening(busy)


def test_the_last_digest_of_a_push_is_taken() -> None:
    output = (
        "The push refers to repository [127.0.0.1:1/sidekick]\n"
        "from: digest: sha256:" + "1" * 64 + " size: 1\n"
        "to: digest: " + DIGEST + " size: 2\n"
        "digest: sha256:short\n"
    )
    assert drillpolicy.pushed_digest(output) == DIGEST
    assert drillpolicy.pushed_digest("no digest here\n") is None
    assert drillpolicy.pushed_digest("") is None


def test_the_release_versions_are_the_source_version_and_the_next_patch(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.9.9"\n', encoding="utf-8")
    assert drillpolicy.release_versions(pyproject) == ("0.9.9", "0.9.10")
    real = drillpolicy.release_versions(REPO_ROOT / "backend" / "pyproject.toml")
    assert all(part.isdigit() for version in real for part in version.split("."))


def test_the_commands_print_what_drill_sh_reads(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    assert cli.main(["drill-reserved-ports", " 030000, 9000"]) == 0
    assert capsys.readouterr().out == "30000\n9000\n"
    assert cli.main(["drill-image-pair", "--from", FROM, "--to", TO]) == 0
    assert cli.main(["drill-pick-port", "--reserved", "55432 55433", "--used", ""]) == 0
    assert 20000 <= int(capsys.readouterr().out) <= 39999
    monkeypatch.setattr(sys, "stdin", io.StringIO("digest: " + DIGEST + " size: 1\n"))
    assert cli.main(["drill-pushed-digest"]) == 0
    assert capsys.readouterr().out == DIGEST + "\n"
    monkeypatch.setattr(sys, "stdin", io.StringIO("nothing\n"))
    assert cli.main(["drill-pushed-digest"]) == 1
    assert capsys.readouterr().out == ""
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "1.2.3"\n', encoding="utf-8")
    assert cli.main(["drill-release-versions", str(pyproject)]) == 0
    assert capsys.readouterr().out == "1.2.3 1.2.4\n"


def test_a_refusal_exits_with_2_and_the_reason_on_stderr(
    capsys: pytest.CaptureFixture[str],
) -> None:
    assert cli.main(["drill-reserved-ports", "abc"]) == 2
    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == "SIDEKICK_RESERVED_PORTS must be comma-separated TCP ports (1-65535)\n"
    assert cli.main(["drill-image-pair", "--from", FROM, "--to", FROM]) == 2
    assert capsys.readouterr().err == "drill: --from-image and --to-image must differ\n"


def test_a_pick_with_every_port_taken_exits_1(
    capsys: pytest.CaptureFixture[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(drillpolicy, "pick_port", lambda *_args: None)
    assert cli.main(["drill-pick-port"]) == 1
    assert capsys.readouterr().err == "drill: no free port found\n"


def _default_signal_handlers() -> None:
    for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(number, signal.SIG_DFL)


def test_the_commands_run_the_way_drill_sh_starts_them() -> None:
    def run(*args: str, stdin: str = "") -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [sys.executable, "-m", "workctl", *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=60,
            env={**os.environ, "PYTHONPATH": str(Path(REPO_ROOT, "tools"))},
            # A run under nohup ignores SIGHUP, and an ignored signal stays ignored in the child.
            preexec_fn=_default_signal_handlers,
            check=False,
        )

    ports = run("drill-reserved-ports", " 030000, 9000")
    assert (ports.returncode, ports.stdout) == (0, "30000\n9000\n")
    refused = run("drill-image-pair", "--from", FROM, "--to", FROM)
    assert refused.returncode == 2
    assert refused.stderr == "drill: --from-image and --to-image must differ\n"
    digest = run("drill-pushed-digest", stdin="digest: " + DIGEST + " size: 1\n")
    assert (digest.returncode, digest.stdout) == (0, DIGEST + "\n")
    assert run("drill-pushed-digest", stdin="nothing\n").returncode == 1
