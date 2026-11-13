"""The step-duration tables of tools/drill.sh: records, plain table and job-summary table."""

import io
import os
import signal
import subprocess
import sys
from pathlib import Path

import pytest
from tools.workctl import cli, drilltimings

from tests.selfhost.work_package.support import REPO_ROOT

RECORDS = "PASS selfhost/install 12\nFAIL selfhost/marker 3\n"


def test_parse_reads_the_records_in_order_and_skips_blank_lines() -> None:
    assert drilltimings.parse(["PASS a/x 1", "", "  ", "FAIL b/y 20"]) == [
        drilltimings.Timing("PASS", "a/x", 1),
        drilltimings.Timing("FAIL", "b/y", 20),
    ]


@pytest.mark.parametrize("line", ["PASS a/x", "PASS a/x 1 2", "PASS a/x one", "PASS a/x -1"])
def test_parse_refuses_a_record_that_is_not_status_step_seconds(line: str) -> None:
    with pytest.raises(ValueError, match="not a timing record"):
        drilltimings.parse([line])


def test_the_plain_table_lists_every_step_and_the_total() -> None:
    assert drilltimings.text_table(drilltimings.parse(RECORDS.splitlines())) == [
        "TIMINGS (seconds):",
        "  PASS selfhost/install 12",
        "  FAIL selfhost/marker 3",
        "  total 15",
    ]


def test_the_job_summary_table_has_a_row_per_step_and_the_total() -> None:
    assert drilltimings.markdown_table(drilltimings.parse(RECORDS.splitlines())) == [
        "### Drill steps",
        "",
        "| Step | Result | Seconds |",
        "| --- | --- | ---: |",
        "| selfhost/install | PASS | 12 |",
        "| selfhost/marker | FAIL | 3 |",
        "| total | | 15 |",
    ]


def test_the_drill_timings_command_prints_the_plain_table_or_the_markdown_one(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO(RECORDS))
    assert cli.main(["drill-timings"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "TIMINGS (seconds):"
    monkeypatch.setattr(sys, "stdin", io.StringIO(RECORDS))
    assert cli.main(["drill-timings", "--markdown"]) == 0
    assert capsys.readouterr().out.splitlines()[0] == "### Drill steps"


def test_the_drill_timings_command_refuses_a_bad_record_with_exit_1(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    monkeypatch.setattr(sys, "stdin", io.StringIO("PASS only-two\n"))
    assert cli.main(["drill-timings"]) == 1
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "not a timing record" in captured.err


def _default_signal_handlers() -> None:
    for number in (signal.SIGTERM, signal.SIGHUP, signal.SIGINT):
        signal.signal(number, signal.SIG_DFL)


def test_the_command_runs_the_way_drill_sh_starts_it() -> None:
    result = subprocess.run(
        [sys.executable, "-m", "workctl", "drill-timings"],
        input=RECORDS,
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, "PYTHONPATH": str(Path(REPO_ROOT, "tools"))},
        # A run under nohup ignores SIGHUP, and an ignored signal stays ignored in the child.
        preexec_fn=_default_signal_handlers,
        check=False,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.splitlines()[-1] == "  total 15"
