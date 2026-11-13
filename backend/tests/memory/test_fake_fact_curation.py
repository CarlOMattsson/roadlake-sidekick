"""The fake provider's single-fact curation: hide, restore and list, as a real provider does."""

from __future__ import annotations

from dataclasses import replace
from uuid import UUID

import pytest

from sidekick.memory.adapters.fake import FakeMemoryProvider
from sidekick.memory.ports import (
    DocumentFact,
    FactCuration,
    MemoryFact,
    MemoryProviderError,
    RetainItem,
)

OWNER = UUID("018af000-0000-7000-8000-0000000000b1")
OTHER_OWNER = UUID("018af000-0000-7000-8000-0000000000b2")
DOC = "v1_" + "c" * 64
ITEM = RetainItem(
    document_id=DOC,
    content="Anna gillar kaffe.\nAnna bor i Lund.",
    timestamp="2026-10-27T08:00:00+00:00",
    entities=("Anna",),
    tags=("k:journal_entry",),
)


def _as_curation(provider: FactCuration) -> FactCuration:
    return provider


def _recalled_texts(provider: FakeMemoryProvider, owner_id: UUID = OWNER) -> list[str]:
    return [fact.text for fact in provider.recall(owner_id=owner_id, query="Anna", max_tokens=512)]


def _fact_id(provider: FakeMemoryProvider, text: str) -> str:
    (fact,) = [
        fact
        for fact in provider.list_document_facts(owner_id=OWNER, document_id=DOC)
        if fact.text == text
    ]
    return fact.id


def test_fake_satisfies_the_curation_port() -> None:
    assert _as_curation(FakeMemoryProvider()) is not None


def test_listing_gives_the_valid_facts_of_one_document() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])

    assert provider.list_document_facts(owner_id=OWNER, document_id=DOC) == (
        DocumentFact(id=f"{DOC}#1", text="Anna gillar kaffe."),
        DocumentFact(id=f"{DOC}#2", text="Anna bor i Lund."),
    )
    assert provider.list_document_facts(owner_id=OWNER, document_id="v1_" + "d" * 64) == ()
    assert provider.list_document_facts(owner_id=OTHER_OWNER, document_id=DOC) == ()


def test_a_hidden_fact_is_left_out_of_recall_and_listing_and_can_be_restored() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    fact_id = _fact_id(provider, "Anna gillar kaffe.")

    assert provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id) == "applied"

    assert _recalled_texts(provider) == ["Anna bor i Lund."]
    assert [
        fact.text for fact in provider.list_document_facts(owner_id=OWNER, document_id=DOC)
    ] == ["Anna bor i Lund."]
    assert provider.restore_fact(owner_id=OWNER, fact_id=fact_id) == "applied"
    assert _recalled_texts(provider) == ["Anna gillar kaffe.", "Anna bor i Lund."]


def test_hiding_and_restoring_twice_is_not_an_error() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    fact_id = _fact_id(provider, "Anna gillar kaffe.")

    assert provider.restore_fact(owner_id=OWNER, fact_id=fact_id) == "applied"
    assert provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id) == "applied"
    assert provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id) == "applied"
    assert _recalled_texts(provider) == ["Anna bor i Lund."]


def test_an_unknown_fact_is_gone() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])

    assert provider.invalidate_fact(owner_id=OWNER, fact_id="nope#1") == "gone"
    assert provider.restore_fact(owner_id=OWNER, fact_id="nope#1") == "gone"


def test_another_owners_fact_cannot_be_hidden() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    fact_id = _fact_id(provider, "Anna gillar kaffe.")

    assert provider.invalidate_fact(owner_id=OTHER_OWNER, fact_id=fact_id) == "gone"
    assert _recalled_texts(provider) == ["Anna gillar kaffe.", "Anna bor i Lund."]


def test_sending_the_same_document_again_changes_nothing_and_keeps_a_hidden_fact_hidden() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    fact_id = _fact_id(provider, "Anna gillar kaffe.")
    provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id)

    provider.retain_batch(owner_id=OWNER, items=[replace(ITEM)])

    assert _recalled_texts(provider) == ["Anna bor i Lund."]
    assert provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id) == "applied"


def test_a_changed_document_gets_new_fact_ids_and_loses_its_hidden_marks() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    old_id = _fact_id(provider, "Anna gillar kaffe.")
    provider.invalidate_fact(owner_id=OWNER, fact_id=old_id)

    provider.retain_batch(
        owner_id=OWNER, items=[replace(ITEM, content="Anna gillar kaffe.\nAnna bor i Malmö.")]
    )

    assert _recalled_texts(provider) == ["Anna gillar kaffe.", "Anna bor i Malmö."]
    new_id = _fact_id(provider, "Anna gillar kaffe.")
    assert new_id != old_id
    assert provider.invalidate_fact(owner_id=OWNER, fact_id=old_id) == "gone"
    assert provider.restore_fact(owner_id=OWNER, fact_id=old_id) == "gone"


def test_a_document_sent_again_after_a_delete_does_not_get_its_old_ids_back() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    old_id = _fact_id(provider, "Anna gillar kaffe.")
    provider.invalidate_fact(owner_id=OWNER, fact_id=old_id)

    provider.delete_document(owner_id=OWNER, document_id=DOC)
    assert provider.list_document_facts(owner_id=OWNER, document_id=DOC) == ()
    assert provider.invalidate_fact(owner_id=OWNER, fact_id=old_id) == "gone"
    provider.retain_batch(owner_id=OWNER, items=[ITEM])

    assert _fact_id(provider, "Anna gillar kaffe.") != old_id
    assert _recalled_texts(provider) == ["Anna gillar kaffe.", "Anna bor i Lund."]


def test_the_calls_are_recorded_without_any_text() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    fact_id = _fact_id(provider, "Anna gillar kaffe.")

    provider.invalidate_fact(owner_id=OWNER, fact_id=fact_id)
    provider.restore_fact(owner_id=OWNER, fact_id=fact_id)

    assert provider.invalidate_calls == [(OWNER, fact_id)]
    assert provider.restore_calls == [(OWNER, fact_id)]


def test_an_unavailable_provider_fails_with_a_content_free_error() -> None:
    provider = FakeMemoryProvider()
    provider.retain_batch(owner_id=OWNER, items=[ITEM])
    provider.available = False

    for call in (
        lambda: provider.invalidate_fact(owner_id=OWNER, fact_id="x#1"),
        lambda: provider.restore_fact(owner_id=OWNER, fact_id="x#1"),
        lambda: provider.list_document_facts(owner_id=OWNER, document_id=DOC),
    ):
        with pytest.raises(MemoryProviderError) as raised:
            call()
        assert raised.value.category == "unavailable"


def test_listing_refuses_a_document_id_that_is_not_opaque() -> None:
    with pytest.raises(ValueError, match="opaque id"):
        FakeMemoryProvider().list_document_facts(owner_id=OWNER, document_id="../x")


def test_a_fact_prints_without_its_text() -> None:
    listed = DocumentFact(id="fact-1", text="Anna gillar kaffe.")
    recalled = MemoryFact(
        id="fact-1",
        text="Anna gillar kaffe.",
        document_id=DOC,
        occurred_start=None,
        occurred_end=None,
    )

    for fact in (listed, recalled):
        assert "Anna" not in repr(fact)
        assert "Anna" not in str(fact)
        assert "fact-1" in repr(fact)
