"""The status helpers of tools/workctl: the version line, the gateway report, and the two probes
that run inside the containers (with the network replaced by fakes)."""

import io
import json
import socket
import subprocess
import sys
import urllib.error
from pathlib import Path
from typing import Any

import pytest
from tools.workctl import cli, probe_egress, probe_gateway, status

from tests.selfhost.work_package.support import REPO_ROOT


def _build_info(tmp_path: Path, **values: object) -> Path:
    info = {
        "commit": "0123456789abcdef",
        "commit_date": "2026-11-11T17:30:00+01:00",
        "built_at": "2026-11-12T10:00:00Z",
        "updated_at": "2026-11-12T12:00:00Z",
        **values,
    }
    path = tmp_path / "build-info.json"
    path.write_text(json.dumps(info), encoding="utf-8")
    return path


def test_version_line_shortens_commit_and_date(tmp_path: Path) -> None:
    assert status.version_line("en", _build_info(tmp_path)) == (
        "version: commit 0123456789 (2026-11-11), built 2026-11-12T10:00:00Z, "
        "last updated 2026-11-12T12:00:00Z"
    )


def test_version_line_in_swedish(tmp_path: Path) -> None:
    assert status.version_line("sv", _build_info(tmp_path)).startswith(
        "version: commit 0123456789 ("
    )


@pytest.mark.parametrize("content", [None, "", "not json", "[]", '{"commit": "abc"}'])
def test_version_line_is_empty_when_the_file_is_missing_or_unusable(
    tmp_path: Path, content: str | None
) -> None:
    path = tmp_path / "build-info.json"
    if content is not None:
        path.write_text(content, encoding="utf-8")
    assert status.version_line("en", path) == ""


def test_version_line_is_empty_for_an_empty_commit(tmp_path: Path) -> None:
    assert status.version_line("en", _build_info(tmp_path, commit="")) == ""


def test_via_report_translates_every_line_kind() -> None:
    output = "models a,b\nmodels_error URLError \noutside 404"
    assert status.via_report("en", output, "") == [
        "  models a,b",
        "  models ERROR URLError ",
        "  outside the base path 404",
    ]


def test_via_report_translates_the_failure_lines_into_swedish() -> None:
    output = "models_error HTTPError 401\noutside_reached\noutside_error URLError"
    assert status.via_report("sv", output, "") == [
        "  modeller FEL HTTPError 401",
        "  utanför bassökvägen NÅDDE",
        "  utanför bassökvägen FEL URLError",
    ]


def test_via_report_confirms_a_listed_model_id() -> None:
    assert status.via_report("en", "models a,b", "b")[-1] == "  model id exists on the server: b"


@pytest.mark.parametrize("wanted", ["", "bb"])
def test_via_report_does_not_confirm_a_partial_id(wanted: str) -> None:
    lines = status.via_report("en", "models a,b,c", wanted)
    assert len(lines) == (1 if not wanted else 2)
    if wanted:
        assert lines[-1].startswith("  WARNING: model id 'bb' is not in the server's list")


def test_via_report_warns_when_the_server_listed_nothing() -> None:
    assert status.via_report("en", "models_error URLError ", "m")[-1].startswith(
        "  WARNING: model id 'm'"
    )


def test_via_report_ignores_unknown_lines() -> None:
    assert status.via_report("en", "noise\n\nmodels x", "") == ["  models x"]


class _Connection:
    def close(self) -> None:
        return None


def _connect_only(allowed: set[str]) -> Any:
    """A stand-in for socket.create_connection that only the given hosts answer."""

    def connect(address: tuple[str, int], timeout: float) -> _Connection:
        assert timeout == probe_egress.TIMEOUT_SECONDS
        if address[0] in allowed:
            return _Connection()
        raise OSError("refused")

    return connect


def _lookup_refused(*_args: object) -> None:
    raise socket.gaierror(-3, "Temporary failure in name resolution")


def test_egress_probe_reports_everything_blocked() -> None:
    lines = probe_egress.probe(
        "model.lan", "8000", "REACHED", "blocked", "the model server directly",
        _connect_only(set()), _lookup_refused,
    )  # fmt: skip
    assert lines == [
        "example.com:443 blocked",
        "1.1.1.1:443 blocked",
        "DNS lookup of example.com blocked (-3)",
        "the model server directly blocked",
    ]


def test_egress_probe_reports_every_open_way_out() -> None:
    lines = probe_egress.probe(
        "model.lan",
        8000,
        "REACHED",
        "blocked",
        "direct",
        _connect_only({"example.com", "1.1.1.1", "model.lan"}),
        lambda *_args: [],
    )
    assert lines == [
        "example.com:443 REACHED",
        "1.1.1.1:443 REACHED",
        "DNS lookup of example.com REACHED",
        "direct REACHED",
    ]


def test_egress_probe_skips_the_direct_line_without_a_host() -> None:
    lines = probe_egress.probe("", "1", "R", "b", "direct", _connect_only(set()), _lookup_refused)
    assert len(lines) == 3 and not any(line.startswith("direct") for line in lines)


class _Response:
    def __init__(self, body: str) -> None:
        self._body = body

    def __enter__(self) -> "_Response":
        return self

    def __exit__(self, *_exc: object) -> None:
        return None

    def read(self, *_size: int) -> bytes:
        return self._body.encode()


def _http_error(code: int) -> urllib.error.HTTPError:
    return urllib.error.HTTPError("http://gw/x", code, "msg", {}, None)  # type: ignore[arg-type]


def test_gateway_probe_lists_models_and_sees_the_outside_path_refused() -> None:
    requests: list[Any] = []

    def urlopen(target: Any, timeout: int) -> Any:
        requests.append(target)
        if not isinstance(target, str):
            return _Response(json.dumps({"data": [{"id": "a"}, {"id": "b"}]}))
        raise _http_error(404)

    lines = probe_gateway.probe(
        "http://gw:8000/v1", {"WORK_MODEL_API_KEY": "synthetic-key"}, urlopen
    )
    assert lines == ["models a,b", "outside 404"]
    assert requests[0].full_url == "http://gw:8000/v1/models"
    assert requests[0].get_header("Authorization") == "Bearer synthetic-key"
    assert requests[1] == "http://gw:8000/not-the-base-path"


def test_gateway_probe_sends_no_authorization_without_a_key() -> None:
    seen: list[Any] = []

    def urlopen(target: Any, timeout: int) -> Any:
        seen.append(target)
        raise _http_error(401)

    lines = probe_gateway.probe("http://gw:8000/v1", {}, urlopen)
    assert lines == ["models_error HTTPError 401", "outside 401"]
    assert not seen[0].has_header("Authorization")


def test_gateway_probe_reports_a_reachable_outside_path_and_other_errors() -> None:
    def urlopen(target: Any, timeout: int) -> Any:
        if isinstance(target, str):
            return _Response("")
        raise urllib.error.URLError("down")

    assert probe_gateway.probe("http://gw/v1", {}, urlopen) == [
        "models_error URLError ",
        "outside_reached",
    ]


def test_gateway_probe_reports_a_failing_outside_request() -> None:
    def urlopen(target: Any, timeout: int) -> Any:
        if isinstance(target, str):
            raise TimeoutError("slow")
        return _Response('{"data": []}')

    assert probe_gateway.probe("http://gw/v1", {}, urlopen) == [
        "models ",
        "outside_error TimeoutError",
    ]


def test_the_gateway_probe_file_runs_as_a_program_the_way_work_sh_passes_it() -> None:
    """work.sh gives the file's text to ``python -c``: it runs as ``__main__`` with the argument."""
    text = (REPO_ROOT / "tools" / "workctl" / "probe_gateway.py").read_text(encoding="utf-8")
    result = subprocess.run(
        [sys.executable, "-c", text, "not-a-url"],
        capture_output=True,
        text=True,
        timeout=60,
        env={"PATH": ""},
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout == "models_error ValueError \noutside_error ValueError\n"


def test_the_egress_probe_file_has_a_main_guard_that_work_sh_s_python_c_triggers() -> None:
    text = (REPO_ROOT / "tools" / "workctl" / "probe_egress.py").read_text(encoding="utf-8")
    compile(text, "probe_egress.py", "exec")
    assert text.rstrip().endswith('if __name__ == "__main__":\n    main(sys.argv)')


def test_the_status_version_command_prints_the_line_or_nothing(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    path = _build_info(tmp_path)
    assert cli.main(["status-version", "--lang", "en", "--build-info", str(path)]) == 0
    assert capsys.readouterr().out.startswith("version: commit 0123456789 (2026-11-11), built ")
    assert cli.main(["status-version", "--build-info", str(tmp_path / "absent.json")]) == 0
    assert capsys.readouterr().out == ""


def test_the_status_via_command_reads_the_probe_output_from_stdin(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("models a,b\noutside 404\n"))
    assert cli.main(["status-via", "--lang", "en", "--wanted-model", "c"]) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[:2] == ["  models a,b", "  outside the base path 404"]
    assert lines[2].startswith("  WARNING: model id 'c' is not in the server's list")
