"""Waiting until the api is ready: the check that runs inside the api container, and the loop around it."""

from __future__ import annotations

import time
from collections.abc import Callable

from .stack import Stack

# Run inside the api container; exit 0 = ready. The same code as READINESS_PY in deploy/selfhost/update.sh and as the
# selfhost api healthcheck (a test keeps them equal). 1) The running api process must answer HTTP within 3 s: 2xx, or
# the intended 404 (the public surface hides /health/* in github_oauth mode); any other status or a hung process fails.
# 2) If the image has the readiness module, the database must answer with the runtime role and the schema must be at
# the image's revision. The container merely being up is not enough.
READINESS_PY = """import importlib.util, sys, urllib.error, urllib.request
try:
    urllib.request.urlopen("http://127.0.0.1:8000/health/live", timeout=3)
except urllib.error.HTTPError as error:
    if error.code != 404:
        sys.exit(1)
except Exception:
    sys.exit(1)
if importlib.util.find_spec("sidekick.shared.readiness") is None:
    sys.exit(0)
from sidekick.shared.readiness import main
main()"""
DEFAULT_TIMEOUT = "180"
DEFAULT_POLL = "3"


def wait_ready(
    stack: Stack,
    clock: Callable[[], float] = time.monotonic,
    sleep: Callable[[float], None] = time.sleep,
) -> bool:
    """True once the api passes the readiness check, False after the timeout
    (SIDEKICK_WORK_READY_TIMEOUT seconds, one try every SIDEKICK_WORK_READY_POLL)."""
    timeout = int(stack.environ.get("SIDEKICK_WORK_READY_TIMEOUT") or DEFAULT_TIMEOUT)
    poll = float(stack.environ.get("SIDEKICK_WORK_READY_POLL") or DEFAULT_POLL)
    deadline = clock() + timeout
    stack.sayf("up_ready_wait", timeout)
    while True:
        if stack.compose("exec", "-T", "api", "python", "-c", READINESS_PY):
            return True
        if clock() >= deadline:
            return False
        sleep(poll)
