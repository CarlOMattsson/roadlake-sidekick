"""Shared by the license tests (D-081): a throwaway owner key pair and log capture."""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date

import pytest
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from sidekick.license.key import LicensePayload, public_key_text, sign_key

OWNER_PRIVATE = Ed25519PrivateKey.generate()
OWNER_PUBLIC = public_key_text(OWNER_PRIVATE.public_key())
STRANGER_PRIVATE = Ed25519PrivateKey.generate()
STRANGER_PUBLIC = public_key_text(STRANGER_PRIVATE.public_key())
LICENSEE = "Kalle Anka Hemlig"


def signed_key(
    *,
    expires: date = date(2099, 1, 1),
    licensee: str = LICENSEE,
    kind: str = "personal",
    key: Ed25519PrivateKey = OWNER_PRIVATE,
) -> str:
    payload = LicensePayload(kind, licensee, date(2000, 1, 1), expires, "id1234")  # type: ignore[arg-type]
    return sign_key(key, payload)


def signature_of(key_text: str) -> str:
    return key_text.split(".")[2]


@contextmanager
def watched(caplog: pytest.LogCaptureFixture) -> Iterator[None]:
    """Capture every Sidekick, web and MCP logger, as the other redaction tests do."""

    caplog.set_level(logging.DEBUG)
    loggers = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in loggers:
        logger.addHandler(caplog.handler)
    try:
        yield
    finally:
        for logger in loggers:
            logger.removeHandler(caplog.handler)


def assert_logs_hold_none_of(caplog: pytest.LogCaptureFixture, *secrets: str) -> None:
    records = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    assert records, "nothing was captured, so nothing was proved"
    for record in records:
        rendered = f"{record.getMessage()} {record.__dict__} {record.exc_text}"
        for secret in secrets:
            assert secret not in rendered, (record.name, record.getMessage())
