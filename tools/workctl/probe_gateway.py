"""Gateway probe of ``work.sh status``. Like ``probe_egress`` it runs INSIDE the api container (``python -c``), with
the standard library only.

It asks the model server through the gateway for its model list (the key comes from the container's own
environment, ``WORK_MODEL_API_KEY``, and is never printed) and requests a path outside the base path, which the
gateway must refuse. It prints neutral lines that ``workctl status-via`` translates on the host:
``models <ids>``, ``models_error <type> <code>``, ``outside <code>``, ``outside_reached``, ``outside_error <type>``.

Argument: the base URL of the model server as the gateway serves it (``http://<gateway>:<port><path>``).
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from collections.abc import Callable, Mapping, Sequence
from typing import Any

TIMEOUT_SECONDS = 10


def probe(
    base: str,
    environ: Mapping[str, str],
    urlopen: Callable[..., Any] = urllib.request.urlopen,
) -> list[str]:
    key = environ.get("WORK_MODEL_API_KEY", "")
    headers = {"Authorization": "Bearer " + key} if key else {}
    lines: list[str] = []
    try:
        request = urllib.request.Request(base + "/models", headers=headers)  # noqa: S310 - http base from work.sh
        with urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            lines.append("models " + ",".join(model["id"] for model in json.load(response).get("data", [])))
    except Exception as error:  # every failure is reported, whatever its kind
        lines.append(f"models_error {type(error).__name__} {getattr(error, 'code', '')}")
    try:
        outside = base.rsplit("/", 1)[0] + "/not-the-base-path"
        urlopen(outside, timeout=TIMEOUT_SECONDS)
        lines.append("outside_reached")
    except urllib.error.HTTPError as error:
        lines.append(f"outside {error.code}")
    except Exception as error:
        lines.append(f"outside_error {type(error).__name__}")
    return lines


def main(argv: Sequence[str]) -> None:
    print("\n".join(probe(argv[1], os.environ)))


if __name__ == "__main__":
    main(sys.argv)
