"""Hostile search input through the use case on PostgreSQL: a result or ValidationError only."""

import pytest

from sidekick.api.app import create_app
from sidekick.search.schemas import SearchResult
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.support.settings import make_settings

ALL_SCOPES = frozenset(
    {"tasks:read", "tasks:write", "projects:read", "contacts:read", "journal:read"}
)

HOSTILE_QUERIES = [
    "och",
    "och att det",
    "the a an",
    "x' OR 1=1 --",
    "'; DROP TABLE tasks; --",
    "a\\b",
    "ab:*",
    "!! ab",
    "<-> ab ()",
    "ab\x00cd",
    "日本語の検索テスト",
    "😀😀 ab",
    "ǅǅ ǆǆ",
    "ab́cd",
    "abc123def",
    "ab_cd",
    "ab-cd e-f",
    "²³ ab",
    "ٱلسلام عليكم",
    "ab" * 50,
    "a\u2010b ab",
    "\u200bab\u200bcd",
    "\uff21\uff22\uff23 \uff46\uff55\uff4c\uff4c",
    "٣٤ ab",
    "ǈ ab",
    "x" * 100,
    "ab퟿",
    "ab\U000e0001cd",
    "ab￿cd",
    "ab﷐ cd",
    "Ⅷ ⅷ ab",
    "ª º ab",
    "ʰʰ ab",
    "ab\u0000",
]


@pytest.mark.integration
@pytest.mark.parametrize("query", HOSTILE_QUERIES)
def test_hostile_query_returns_a_result_or_validation_error(query: str) -> None:
    factory = database_factory()
    container = create_app(make_settings(), factory).state.container
    owner_id = container.auth.provision_user("hostile-search", "Hostile")
    actor = Actor(owner_id, ALL_SCOPES)
    container.tasks.create(
        actor, title="Och hus drift", description=None, idempotency_key="hostile-task"
    )

    try:
        result = container.search.search(actor, query)
    except ValidationError:
        return

    assert isinstance(result, SearchResult)
