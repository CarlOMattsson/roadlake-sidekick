"""An owner export as the previous format (version 4) wrote it, built from a current one."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from sidekick.owner_export.catalogue import PREVIOUS_EXPORT_FORMAT_VERSION, RETIRED_COLLECTIONS
from sidekick.owner_export.document import export_checksum

BASELINE_HEAD = "100_schema_baseline_0_1_0"


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
        **document["collections"],
        **{name: list(rows.get(name, [])) for name in RETIRED_COLLECTIONS},
    }
    counts = {name: len(items) for name, items in collections.items()}
    result: dict[str, Any] = {
        **document,
        "format_version": PREVIOUS_EXPORT_FORMAT_VERSION,
        "schema_head": head,
        "collections": collections,
        "manifest": {"collection_counts": counts},
    }
    result["manifest"]["sha256"] = export_checksum(result)
    return result
