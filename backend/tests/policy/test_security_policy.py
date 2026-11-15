"""The security policy links to the private reporting form, which the OpenSSF Scorecard looks for.

The Scorecard Security-Policy check wants a linked way to report a vulnerability, not only
prose. The files live at the root of the published repository and in tools/export/overlay of this
one.
"""

from pathlib import Path

import pytest

pytestmark = pytest.mark.policy

ROOT = Path(__file__).resolve().parents[3]
REPORT_URL = "https://github.com/CarlOMattsson/roadlake-sidekick/security/advisories/new"
POLICY_URL = "https://github.com/CarlOMattsson/roadlake-sidekick/security/policy"


def _policy(name: str) -> str:
    for path in (ROOT / name, ROOT / "tools" / "export" / "overlay" / name):
        if path.exists():
            return path.read_text(encoding="utf-8")
    raise AssertionError(f"{name} is missing")


@pytest.mark.parametrize("name", ["SECURITY.md", "SECURITY.sv.md"])
def test_the_policy_links_to_private_reporting_and_to_itself(name: str) -> None:
    text = _policy(name)
    assert REPORT_URL in text
    assert POLICY_URL in text
