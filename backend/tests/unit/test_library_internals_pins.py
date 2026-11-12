"""Code that patches or reads library internals is only valid for the versions it was reviewed on.

Each module that does so keeps a reviewed-version constant and checks the library's shape at
startup. These tests fail when the pin (`pyproject.toml`), the lock (`uv.lock`), the installed
library and that constant stop agreeing, so an upgrade cannot slip past the review.
"""

import logging
import tomllib
from importlib import metadata
from pathlib import Path

import pytest
from opentelemetry.sdk.trace import ReadableSpan, TracerProvider

from sidekick.mcp import input_schemas
from sidekick.shared.observability import harden_tracer_provider, sdk_internals, setup
from tests.support import schema_cache

BACKEND = Path(__file__).resolve().parents[2]

REVIEWED = {
    "fastmcp": schema_cache.REVIEWED_FASTMCP_VERSION,
    "mcp": input_schemas.REVIEWED_MCP_VERSION,
    "opentelemetry-sdk": sdk_internals.REVIEWED_OTEL_SDK_VERSION,
}


def _locked_versions() -> dict[str, str]:
    lock = tomllib.loads((BACKEND / "uv.lock").read_text(encoding="utf-8"))
    return {package["name"]: package["version"] for package in lock["package"]}


def _pinned_versions() -> dict[str, str]:
    project = tomllib.loads((BACKEND / "pyproject.toml").read_text(encoding="utf-8"))
    pins: dict[str, str] = {}
    for requirement in project["project"]["dependencies"]:
        name, _, version = requirement.partition("==")
        pins[name] = version
    return pins


@pytest.mark.parametrize("package", sorted(REVIEWED))
def test_the_installed_and_locked_library_is_the_reviewed_one(package: str) -> None:
    assert metadata.version(package) == REVIEWED[package]
    assert _locked_versions()[package] == REVIEWED[package]


@pytest.mark.parametrize("package", ["fastmcp", "opentelemetry-sdk"])
def test_directly_depended_libraries_are_pinned_to_the_reviewed_version(package: str) -> None:
    assert _pinned_versions()[package] == REVIEWED[package]


def test_both_fastmcp_patches_were_reviewed_on_the_same_release() -> None:
    assert schema_cache.REVIEWED_FASTMCP_VERSION == input_schemas.REVIEWED_FASTMCP_VERSION


def test_the_span_rewrite_fields_are_still_read_by_the_sdk() -> None:
    assert sdk_internals.span_rewrite_problem() is None


def test_a_span_field_the_sdk_no_longer_reads_is_reported(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class RenamedEvents(ReadableSpan):
        @property
        def events(self):  # type: ignore[override]  # pyright: ignore[reportIncompatibleVariableOverride]
            return ()

    monkeypatch.setattr(sdk_internals, "ReadableSpan", RenamedEvents)

    assert sdk_internals.span_rewrite_problem() == "_events"


def test_redaction_is_not_installed_when_the_sdk_internals_changed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    provider = TracerProvider()
    chain = provider._active_span_processor  # pyright: ignore[reportPrivateUsage]
    original = chain.on_end
    monkeypatch.setattr(setup, "span_rewrite_problem", lambda: "_events")

    messages: list[str] = []

    class Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            messages.append(record.getMessage())

    logger = logging.getLogger("sidekick.observability")
    handler = Collector(level=logging.ERROR)
    logger.addHandler(handler)
    try:
        installed = harden_tracer_provider(provider)
    finally:
        logger.removeHandler(handler)

    assert installed is False
    assert chain.on_end == original
    assert messages == ["span_rewrite_internals_changed: _events"]
