"""An owner export as an earlier format (4, 5, 6 or 7) wrote it, built from a current one."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidekick.owner_export.catalogue import (
    COLLECTIONS_ADDED_IN_FORMAT_6,
    COLLECTIONS_ADDED_IN_FORMAT_8,
    COLUMNS_ADDED_IN_FORMAT_7,
    COLUMNS_ADDED_IN_FORMAT_8,
    FORMAT_WITH_RETIRED_COLLECTIONS,
    FORMAT_WITHOUT_AI_STEPS,
    FORMAT_WITHOUT_TAG_LINKS,
    FORMAT_WITHOUT_TASK_REVIEW,
    RETIRED_COLLECTIONS,
    excluded_collections_for,
)
from sidekick.owner_export.document import export_checksum

BASELINE_HEAD = "100_schema_baseline_0_1_0"
DROP_AUTOMATION_HEAD = "106_drop_retired_automation_tables"
TAG_LINKS_HEAD = "107_contact_and_journal_entry_tags"
FORGOTTEN_FACTS_HEAD = "108_memory_forgotten_facts"


def _resealed(
    document: Mapping[str, Any], format_version: int, head: str, collections: Mapping[str, Any]
) -> dict[str, Any]:
    counts = {name: len(items) for name, items in collections.items()}
    result: dict[str, Any] = {
        **document,
        "format_version": format_version,
        "schema_head": head,
        "excluded": excluded_collections_for(head),
        "collections": dict(collections),
        "manifest": {"collection_counts": counts},
    }
    result["manifest"]["sha256"] = export_checksum(result)
    return result


HEAD_110 = "110_task_ambition"
HEAD_111 = "111_webhook_tokens"


def _without_columns(
    collections: Mapping[str, Any], columns: Mapping[str, frozenset[str]]
) -> dict[str, Any]:
    return {
        name: [
            {
                field: value
                for field, value in row.items()
                if field not in columns.get(name, frozenset())
            }
            for row in rows
        ]
        for name, rows in collections.items()
    }


def _format_7_collections(document: Mapping[str, Any]) -> dict[str, Any]:
    """The collections without what format 8 added: the AI columns and the run collection."""

    return _without_columns(
        {
            name: rows
            for name, rows in document["collections"].items()
            if name not in COLLECTIONS_ADDED_IN_FORMAT_8
        },
        COLUMNS_ADDED_IN_FORMAT_8,
    )


def _format_6_collections(document: Mapping[str, Any]) -> dict[str, Any]:
    """The collections without the columns format 7 added (a Task's `last_reviewed_at`)."""

    return _without_columns(_format_7_collections(document), COLUMNS_ADDED_IN_FORMAT_7)


def _without_tag_links(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: rows
        for name, rows in _format_6_collections(document).items()
        if name not in COLLECTIONS_ADDED_IN_FORMAT_6
    }


def as_format_7(document: Mapping[str, Any], head: str = HEAD_111) -> dict[str, Any]:
    """The document without the AI columns and runs of format 8, stamped with `head` and sealed
    again."""

    return _resealed(document, FORMAT_WITHOUT_AI_STEPS, head, _format_7_collections(document))


def as_format_6(document: Mapping[str, Any], head: str = FORGOTTEN_FACTS_HEAD) -> dict[str, Any]:
    """The document without the review column of Tasks, stamped with `head` and sealed again."""

    return _resealed(document, FORMAT_WITHOUT_TASK_REVIEW, head, _format_6_collections(document))


def as_format_5(document: Mapping[str, Any], head: str = DROP_AUTOMATION_HEAD) -> dict[str, Any]:
    """The document without the tag links of Contacts and Journal entries, stamped with `head`
    and sealed again."""

    return _resealed(document, FORMAT_WITHOUT_TAG_LINKS, head, _without_tag_links(document))


def as_format_4(
    document: Mapping[str, Any],
    head: str = BASELINE_HEAD,
    retired_rows: Mapping[str, list[Any]] | None = None,
) -> dict[str, Any]:
    """The document with the four retired collections, stamped with `head` and sealed again.

    `retired_rows` puts rows into some of the retired collections (they are empty otherwise).
    """

    rows = retired_rows or {}
    collections = {
        **_without_tag_links(document),
        **{name: list(rows.get(name, [])) for name in RETIRED_COLLECTIONS},
    }
    return _resealed(document, FORMAT_WITH_RETIRED_COLLECTIONS, head, collections)
