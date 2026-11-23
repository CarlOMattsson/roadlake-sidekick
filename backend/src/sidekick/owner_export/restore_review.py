"""What a restore does with repetition: it refuses cards that name the wrong source and can check
that every card's schedule is what folding its answers gives.

A card must name exactly the source its kind says, the same rule the table's CHECK holds, so the
refusal comes with the plan and not from the middle of the write. The refusal names the row
position, never content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any
from uuid import UUID

from sidekick.owner_export.catalogue import ExportRefused
from sidekick.review.domain.cards import CardSource, FoldReport
from sidekick.review.domain.scheduling import ReviewConfig
from sidekick.review.persistence import ReviewStore
from sidekick.shared.types import TxSession


def _names_its_source(row: Mapping[str, Any]) -> bool:
    contact, fact = row.get("contact_id"), row.get("library_fact_id")
    kind = row.get("source_kind")
    if kind == CardSource.CONTACT_FACE.value:
        return contact is not None and fact is None
    if kind == CardSource.LIBRARY_FACT.value:
        return fact is not None and contact is None
    return False


def require_consistent_cards(cards: list[Mapping[str, Any]]) -> None:
    """Refuse a card whose kind and source key disagree."""

    for position, row in enumerate(cards):
        if not _names_its_source(row):
            raise ExportRefused(
                f"export has a card that names the wrong source: review_cards[{position}]"
            )


def refold_report(session: TxSession, owner_id: UUID) -> FoldReport:
    """Fold every restored card's answers again, under the owner's own settings, and count the
    cards whose stored schedule differs. Writes nothing."""

    settings = ReviewStore.get_settings(session, owner_id)
    config = ReviewConfig() if settings is None else settings.config
    return ReviewStore.verify_cards(session, owner_id, config)
