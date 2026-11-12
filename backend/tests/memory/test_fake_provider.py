"""Deterministic fake memory provider: one line of a document is one fact (no network, no DB)."""

from __future__ import annotations

from collections.abc import Callable
from uuid import UUID

import pytest

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.ports import MemoryFact, MemoryProvider, MemoryProviderError, RetainItem

OWNER = UUID("018af000-0000-7000-8000-0000000000b1")
OTHER_OWNER = UUID("018af000-0000-7000-8000-0000000000b2")
DOC = "v1_" + "c" * 64
OTHER_DOC = "v1_" + "d" * 64
JOURNAL = RetainItem(
    document_id=DOC,
    content="Jag sprang en mil.\n\nKänner mig lugn idag.\n   \nMötte Anna.",
    timestamp="2026-10-27T08:00:00+00:00",
    entities=("Anna",),
    tags=("k:journal_entry",),
)


def _as_port(provider: MemoryProvider) -> MemoryProvider:
    return provider


def test_fake_satisfies_the_memory_port() -> None:
    assert _as_port(FakeMemoryProvider()) is not None


def test_fake_reports_its_provider_name_through_the_port() -> None:
    assert _as_port(FakeMemoryProvider()).provider_name == "fake"


def test_one_non_empty_line_becomes_one_fact_with_its_document_and_event_time() -> None:
    provider = FakeMemoryProvider()

    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])
    facts = provider.recall(owner_id=OWNER, query="lugn Anna sprang", max_tokens=512)

    assert facts == (
        MemoryFact(
            id=f"{DOC}#1",
            text="Jag sprang en mil.",
            document_id=DOC,
            occurred_start="2026-10-27T08:00:00+00:00",
            occurred_end="2026-10-27T08:00:00+00:00",
            fact_type="world",
        ),
        MemoryFact(
            id=f"{DOC}#2",
            text="Känner mig lugn idag.",
            document_id=DOC,
            occurred_start="2026-10-27T08:00:00+00:00",
            occurred_end="2026-10-27T08:00:00+00:00",
            fact_type="world",
        ),
        MemoryFact(
            id=f"{DOC}#3",
            text="Mötte Anna.",
            document_id=DOC,
            occurred_start="2026-10-27T08:00:00+00:00",
            occurred_end="2026-10-27T08:00:00+00:00",
            fact_type="world",
        ),
    )


def test_unset_timestamp_gives_facts_without_an_event_time() -> None:
    provider = FakeMemoryProvider()
    contact = RetainItem(
        document_id=DOC, content="Anna", timestamp="unset", entities=(), tags=("k:contact",)
    )

    provider.retain_batch(owner_id=OWNER, items=[contact])
    facts = provider.recall(owner_id=OWNER, query="Anna", max_tokens=64)

    assert [(fact.occurred_start, fact.occurred_end) for fact in facts] == [(None, None)]


def test_retain_replaces_the_facts_of_the_same_document() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])
    edited = RetainItem(
        document_id=DOC,
        content="Jag cyklade istället.",
        timestamp="2026-10-27T08:00:00+00:00",
        entities=(),
        tags=(),
    )

    provider.retain_batch(owner_id=OWNER, items=[edited])

    assert provider.recall(owner_id=OWNER, query="sprang", max_tokens=64) == ()
    assert [
        fact.text for fact in provider.recall(owner_id=OWNER, query="cyklade", max_tokens=64)
    ] == ["Jag cyklade istället."]


def test_recall_is_scoped_to_the_owner() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])

    assert provider.recall(owner_id=OTHER_OWNER, query="Anna", max_tokens=64) == ()


def test_recall_with_no_usable_terms_returns_nothing() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])

    assert provider.recall(owner_id=OWNER, query="   ", max_tokens=64) == ()


def test_recall_respects_the_token_budget() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])

    facts = provider.recall(owner_id=OWNER, query="jag mig Anna", max_tokens=1)

    assert len(facts) < 3


def test_delete_removes_the_document_and_missing_delete_is_a_no_op() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL])

    provider.delete_document(owner_id=OWNER, document_id=DOC)
    provider.delete_document(owner_id=OWNER, document_id=DOC)

    assert provider.recall(owner_id=OWNER, query="Anna", max_tokens=64) == ()
    assert provider.delete_calls == [(OWNER, DOC), (OWNER, DOC)]


def test_delete_only_affects_the_given_document() -> None:
    provider = FakeMemoryProvider()
    other = RetainItem(
        document_id=OTHER_DOC, content="Anna är kvar", timestamp="unset", entities=(), tags=()
    )
    provider.retain_batch(owner_id=OWNER, items=[JOURNAL, other])

    provider.delete_document(owner_id=OWNER, document_id=DOC)

    assert [
        fact.document_id for fact in provider.recall(owner_id=OWNER, query="Anna", max_tokens=64)
    ] == [OTHER_DOC]


def test_retain_returns_an_operation_that_is_retained() -> None:
    provider = FakeMemoryProvider()

    operation_id = provider.retain_batch(owner_id=OWNER, items=[JOURNAL])

    assert provider.operation_status(owner_id=OWNER, operation_id=operation_id).state == "retained"
    assert len(provider.retain_calls) == 1
    assert provider.retain_calls[0].owner_id == OWNER
    assert provider.retain_calls[0].items == (JOURNAL,)


def test_unknown_operation_is_reported_as_lost() -> None:
    provider = FakeMemoryProvider()

    result = provider.operation_status(owner_id=OWNER, operation_id="fake-op-999999")

    assert (result.state, result.failure_category) == ("failed", "operation_lost")


@pytest.mark.parametrize(
    ("items_factory", "message"),
    [
        (lambda: [], "batch size"),
        (
            lambda: [
                RetainItem(document_id=DOC, content=" ", timestamp="unset", entities=(), tags=())
            ],
            "cannot be empty",
        ),
        (
            lambda: [
                RetainItem(document_id=DOC, content="a", timestamp="unset", entities=(), tags=()),
                RetainItem(document_id=DOC, content="b", timestamp="unset", entities=(), tags=()),
            ],
            "repeats",
        ),
        (
            lambda: [
                RetainItem(
                    document_id="../documents", content="a", timestamp="unset", entities=(), tags=()
                )
            ],
            "opaque id",
        ),
    ],
)
def test_fake_rejects_exactly_what_the_real_adapter_rejects(
    items_factory: Callable[[], list[RetainItem]], message: str
) -> None:
    provider = FakeMemoryProvider()

    with pytest.raises(ValueError, match=message):
        provider.retain_batch(owner_id=OWNER, items=items_factory())
    assert provider.retain_calls == []


def test_unavailable_provider_fails_with_a_category_and_reports_unhealthy() -> None:
    provider = FakeMemoryProvider(available=False)

    assert provider.health() is False
    with pytest.raises(MemoryProviderError) as error:
        provider.recall(owner_id=OWNER, query="Anna", max_tokens=64)
    assert error.value.category == "unavailable"
    with pytest.raises(MemoryProviderError):
        provider.retain_batch(owner_id=OWNER, items=[JOURNAL])
    assert provider.retain_calls == []


def test_healthy_fake_reports_healthy() -> None:
    assert FakeMemoryProvider().health() is True
