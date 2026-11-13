"""The owner-export document: canonical JSON, the integrity checksum and verification."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Any, cast
from uuid import UUID

from sidekick.owner_export.catalogue import (
    ACCEPTED_SCHEMA_HEADS_BY_FORMAT,
    COLLECTIONS_ADDED_IN_FORMAT_6,
    EXCLUDED_COLLECTIONS,
    EXPORT_FORMAT,
    EXPORT_FORMAT_VERSION,
    FORMAT_WITH_RETIRED_COLLECTIONS,
    FORMAT_WITHOUT_TAG_LINKS,
    RETIRED_COLLECTIONS,
    SCHEMA_HEAD,
    SOURCES_BY_NAME,
    ExportRefused,
    source_fields,
)
from sidekick.work.domain.context import DOMAIN_ACCENTS


def json_safe(value: Any) -> Any:
    if isinstance(value, (UUID, datetime, date)):
        return str(value) if isinstance(value, UUID) else value.isoformat()
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, Mapping):
        mapping = cast(Mapping[object, Any], value)
        return {str(key): json_safe(item) for key, item in mapping.items()}
    if isinstance(value, (list, tuple)):
        sequence = cast(list[Any] | tuple[Any, ...], value)
        return [json_safe(item) for item in sequence]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    raise TypeError(f"unsupported export value: {type(value).__name__}")


def canonical_json(value: Mapping[str, Any]) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _without_checksum(document: Mapping[str, Any]) -> dict[str, Any]:
    manifest_value = document.get("manifest")
    if not isinstance(manifest_value, Mapping):
        raise ExportRefused("manifest must be an object")
    manifest = cast(Mapping[str, Any], manifest_value)
    return {
        **document,
        "manifest": {
            "collection_counts": manifest.get("collection_counts"),
        },
    }


def export_checksum(document: Mapping[str, Any]) -> str:
    return hashlib.sha256(canonical_json(_without_checksum(document))).hexdigest()


class ExportBudget:
    """A byte budget charged row by row while an export is serialised.

    Each row is charged its canonical-JSON size, which is a lower bound of the final document, so
    the first row that takes the total over `limit` ends the export with the error `exceeded`
    builds, before the rest of the data has been read or copied.  The caller picks the error, so
    the export stays free of the backup module's classes.
    """

    def __init__(self, limit: int, exceeded: Callable[[], Exception]) -> None:
        self._limit = limit
        self._exceeded = exceeded
        self._spent = 0

    def charge(self, row: Mapping[str, Any]) -> None:
        self._spent += len(canonical_json(row))
        if self._spent > self._limit:
            raise self._exceeded()


def assemble_export_document(
    owner_id: UUID,
    normalized_collections: dict[str, list[Any]],
    *,
    exported_at: datetime,
) -> dict[str, Any]:
    """Wrap collections whose rows are already JSON-safe in the checksummed export document."""

    counts = {name: len(normalized_collections[name]) for name in normalized_collections}
    document: dict[str, Any] = {
        "format": EXPORT_FORMAT,
        "format_version": EXPORT_FORMAT_VERSION,
        "schema_head": SCHEMA_HEAD,
        "owner_id": str(owner_id),
        "exported_at": exported_at.isoformat(),
        "collections": normalized_collections,
        "excluded": list(EXCLUDED_COLLECTIONS),
        "manifest": {"collection_counts": counts},
    }
    document["manifest"] = {"collection_counts": counts, "sha256": export_checksum(document)}
    return document


def build_export_document(
    owner_id: UUID,
    collections: Mapping[str, list[Mapping[str, Any]]],
    *,
    exported_at: datetime,
) -> dict[str, Any]:
    normalized_collections = {
        name: [json_safe(dict(row)) for row in rows] for name, rows in collections.items()
    }
    return assemble_export_document(owner_id, normalized_collections, exported_at=exported_at)


@dataclass(frozen=True, slots=True)
class ExportVerification:
    owner_id: UUID
    checksum: str
    collection_counts: dict[str, int]


def verify_export(document: Mapping[str, Any]) -> ExportVerification:
    if document.get("format") != EXPORT_FORMAT:
        raise ExportRefused("unsupported export format")
    format_version = document.get("format_version")
    if (
        not isinstance(format_version, int)
        or isinstance(format_version, bool)
        or format_version not in ACCEPTED_SCHEMA_HEADS_BY_FORMAT
    ):
        raise ExportRefused("unsupported export version")
    if document.get("schema_head") not in ACCEPTED_SCHEMA_HEADS_BY_FORMAT[format_version]:
        raise ExportRefused("unsupported schema head")
    if not isinstance(document.get("exported_at"), str):
        raise ExportRefused("invalid export timestamp")
    try:
        owner_id = UUID(str(document["owner_id"]))
    except (KeyError, TypeError, ValueError) as error:
        raise ExportRefused("invalid owner id") from error

    collections_value = document.get("collections")
    if not isinstance(collections_value, Mapping):
        raise ExportRefused("collections must be an object")
    collections = cast(Mapping[str, Any], collections_value)
    retired: frozenset[str] = (
        RETIRED_COLLECTIONS if format_version == FORMAT_WITH_RETIRED_COLLECTIONS else frozenset()
    )
    # A document of an older format does not have the collections added since; they restore empty.
    not_yet: frozenset[str] = (
        COLLECTIONS_ADDED_IN_FORMAT_6 if format_version <= FORMAT_WITHOUT_TAG_LINKS else frozenset()
    )
    if set(collections) != (set(SOURCES_BY_NAME) - not_yet) | retired:
        raise ExportRefused("export collection catalogue does not match format")
    for name in sorted(retired):
        if collections[name] != []:
            raise ExportRefused(f"collection {name} of a retired feature must be empty")

    for name, source in SOURCES_BY_NAME.items():
        if name in not_yet:
            continue
        rows_value = collections[name]
        if not isinstance(rows_value, list):
            raise ExportRefused(f"collection {name} must be an array")
        rows = cast(list[Any], rows_value)
        fields = set(source_fields(source))
        for row_value in rows:
            if not isinstance(row_value, Mapping):
                raise ExportRefused(f"collection {name} contains a non-object row")
            row = cast(Mapping[str, Any], row_value)
            if set(row) != fields:
                raise ExportRefused(f"collection {name} has an unexpected row shape")
            if row.get("owner_id") != str(owner_id):
                raise ExportRefused(f"collection {name} crosses the owner boundary")
            # The accent is a closed palette, mirroring the domain entity and the DB CHECK.
            if name == "domains" and row.get("accent") not in (None, *DOMAIN_ACCENTS):
                raise ExportRefused(f"collection {name} has an invalid domain accent")

    excluded = document.get("excluded")
    if excluded != list(EXCLUDED_COLLECTIONS):
        raise ExportRefused("export exclusion catalogue does not match format")
    manifest_value = document.get("manifest")
    if not isinstance(manifest_value, Mapping):
        raise ExportRefused("manifest must be an object")
    manifest = cast(Mapping[str, Any], manifest_value)
    counts = manifest.get("collection_counts")
    if counts != {name: len(collections[name]) for name in collections}:
        raise ExportRefused("manifest counts do not match collections")
    document_counts = {name: len(collections.get(name, ())) for name in SOURCES_BY_NAME}
    checksum = manifest.get("sha256")
    if not isinstance(checksum, str) or checksum != export_checksum(document):
        raise ExportRefused("export checksum mismatch")
    return ExportVerification(owner_id, checksum, document_counts)
