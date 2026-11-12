"""Shared test helpers moved out of `tests/mcp/test_journal_write_entry.py`."""

from typing import Any

from sidekick.api.app import create_container
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings
from tests.support.telemetry import CaptureTelemetry

FULL = frozenset({"journal:read", "journal:write", "projects:read", "tasks:read", "contacts:read"})


SETUP = FULL | {"projects:write", "tasks:write", "contacts:write"}


def make_container(telemetry: CaptureTelemetry | None = None) -> tuple[Any, Actor]:
    container = create_container(make_settings(), database_factory(), telemetry)
    user_id = container.auth.provision_user("write-entry-owner", "Write Entry Owner")
    return container, Actor(user_id, FULL)


def make_project(container: Any, user_id: Any, key: str) -> Any:
    setup = Actor(user_id, SETUP)
    domain = container.contexts.create_domain(
        setup, name="Ops", description=None, idempotency_key=f"{key}-domain"
    )
    return container.projects.create(
        setup, title="Projekt", domain_id=domain.id, idempotency_key=key
    )


def args(key: str, **overrides: Any) -> dict[str, Any]:
    return {
        "journal_date": "2026-10-28",
        "title": "En bra dag",
        "source_text": "Jag pratade med Anna och bestämde att flytta mötet.",
        "summary": "Pratade med Anna.",
        "key_points": [{"kind": "decision", "text": "Flytta mötet."}],
        "idempotency_key": key,
        **overrides,
    }
