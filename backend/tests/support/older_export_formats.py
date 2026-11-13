"""An owner export as an earlier format (version 4 or 5) wrote it, built from a current one."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidekick.owner_export.catalogue import (
    COLLECTIONS_ADDED_IN_FORMAT_6,
    FORMAT_WITH_RETIRED_COLLECTIONS,
    FORMAT_WITHOUT_TAG_LINKS,
    RETIRED_COLLECTIONS,
)
from sidekick.owner_export.document import export_checksum

BASELINE_HEAD = "100_schema_baseline_0_1_0"
DROP_AUTOMATION_HEAD = "106_drop_retired_automation_tables"


def _resealed(
    document: Mapping[str, Any], format_version: int, head: str, collections: Mapping[str, Any]
) -> dict[str, Any]:
    counts = {name: len(items) for name, items in collections.items()}
    result: dict[str, Any] = {
        **document,
        "format_version": format_version,
        "schema_head": head,
        "collections": dict(collections),
        "manifest": {"collection_counts": counts},
    }
    result["manifest"]["sha256"] = export_checksum(result)
    return result


def _without_tag_links(document: Mapping[str, Any]) -> dict[str, Any]:
    return {
        name: rows
        for name, rows in document["collections"].items()
        if name not in COLLECTIONS_ADDED_IN_FORMAT_6
    }


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
