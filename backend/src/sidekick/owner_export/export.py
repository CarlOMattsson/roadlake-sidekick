"""The authenticated owner's export, built from one consistent snapshot of the database."""

from __future__ import annotations

from datetime import datetime
from typing import Any
from uuid import UUID

from sidekick.owner_export.catalogue import EXPORT_SOURCES, source_fields
from sidekick.owner_export.document import (
    ExportBudget,
    assemble_export_document,
    json_safe,
    verify_export,
)
from sidekick.owner_export.persistence import all_owner_ids
from sidekick.shared.observability import NoopTelemetryAdapter, TelemetryPort
from sidekick.shared.types import Actor, Clock, SystemClock, TxSession


class OwnerExportService:
    """Application service for an authenticated owner's complete export."""

    def __init__(
        self,
        store: Any,
        clock: Clock | None = None,
        telemetry: TelemetryPort | None = None,
    ) -> None:
        self._store = store
        self._clock = clock or SystemClock()
        self._telemetry = telemetry or NoopTelemetryAdapter()

    def _export_owner_in_session(
        self,
        session: TxSession,
        owner_id: UUID,
        *,
        exported_at: datetime,
        budget: ExportBudget | None = None,
    ) -> dict[str, Any]:
        collections: dict[str, list[Any]] = {}
        for source in EXPORT_SOURCES:
            fields = source_fields(source)
            exported: list[Any] = []
            # The rows are read as a stream and each one is turned into its JSON-safe form once,
            # so no second copy of the data is built and an over-budget export stops here.
            for row in self._store.export_owner_rows(
                session,
                owner_id=owner_id,
                row_type=source.row_type,
            ):
                document_row = {field: json_safe(getattr(row, field)) for field in fields}
                if budget is not None:
                    budget.charge(document_row)
                exported.append(document_row)
            collections[source.name] = exported
        return assemble_export_document(owner_id, collections, exported_at=exported_at)

    def export(self, actor: Actor) -> dict[str, Any]:
        def read(session: TxSession) -> dict[str, Any]:
            return self._export_owner_in_session(
                session, actor.user_id, exported_at=self._clock.now()
            )

        document = self._store.snapshot_transaction(read)

        verification = verify_export(document)
        self._telemetry.count(
            "sidekick.owner_export",
            {
                "owner_export.operation": "export",
                "outcome": "success",
                "owner_export.collection_count": str(len(verification.collection_counts)),
            },
        )
        return document

    def export_all(self, budget: ExportBudget | None = None) -> list[dict[str, Any]]:
        """Export every owner from one repeatable-read snapshot of the database.

        With a `budget`, the export is abandoned with the budget's error as soon as the rows read
        so far are over it.
        """

        def read(session: TxSession) -> list[dict[str, Any]]:
            exported_at = self._clock.now()
            owner_ids = all_owner_ids(session)
            return [
                self._export_owner_in_session(
                    session, owner_id, exported_at=exported_at, budget=budget
                )
                for owner_id in owner_ids
            ]

        documents = self._store.snapshot_transaction(read)
        for document in documents:
            verify_export(document)
        return documents
