"""The step-duration tables of tools/drill.sh: the plain table and the job-summary table."""

from tools.workctl import drilltimings

TIMINGS = [
    drilltimings.Timing("PASS", "selfhost/install", 12),
    drilltimings.Timing("FAIL", "selfhost/marker", 3),
]


def test_the_plain_table_lists_every_step_and_the_total() -> None:
    assert drilltimings.text_table(TIMINGS) == [
        "TIMINGS (seconds):",
        "  PASS selfhost/install 12",
        "  FAIL selfhost/marker 3",
        "  total 15",
    ]


def test_the_job_summary_table_has_a_row_per_step_and_the_total() -> None:
    assert drilltimings.markdown_table(TIMINGS) == [
        "### Drill steps",
        "",
        "| Step | Result | Seconds |",
        "| --- | --- | ---: |",
        "| selfhost/install | PASS | 12 |",
        "| selfhost/marker | FAIL | 3 |",
        "| total | | 15 |",
    ]
