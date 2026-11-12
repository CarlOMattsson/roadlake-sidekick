"""The shared wrapper of a feature write: one transaction, one idempotency record, telemetry.

Shopping and external references run every write the same way: check the idempotency key,
open a trace span, run the work once per (actor, operation, key) inside one transaction, count
the outcome and log one content-free line. Only the feature name and the work differ, so the
wrapper lives here once. Spans, counters and logs carry the feature name, the operation name,
the outcome and the correlation id, never record content.
"""

import logging
from collections.abc import Callable
from typing import Any, Protocol
from uuid import UUID

from sidekick.shared.errors import ValidationError
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.types import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MIN_IDEMPOTENCY_KEY_LENGTH,
    IdempotentStore,
    TransactionalStore,
    TxSession,
)


class IdempotentTransactionalStore(IdempotentStore, TransactionalStore, Protocol):
    """A store that opens a transaction and records one outcome per idempotency key."""


def run_idempotent_operation(
    *,
    store: IdempotentTransactionalStore,
    telemetry: TelemetryPort,
    logger: logging.Logger,
    feature: str,
    actor_id: UUID,
    operation: str,
    key: str,
    payload: dict[str, Any],
    execute: Callable[[TxSession], dict[str, Any]],
    correlation_id: str | None,
    replay: Callable[[dict[str, Any]], dict[str, Any]] | None = None,
    rebuild: Callable[[TxSession, dict[str, Any]], dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Run `execute` once for this idempotency key inside a traced transaction.

    `feature` names the area (for example `shopping`): it prefixes the idempotency operation
    name and the span, counter and log event names. The key is validated before anything runs.
    Without `replay` the result is stored whole, which the store allows only for identifier-only
    operations. With `replay` only that projection is kept (first call and retry alike), and
    `rebuild` re-reads the rest by id so a retry never returns a stored copy of names or notes.
    """

    if not MIN_IDEMPOTENCY_KEY_LENGTH <= len(key) <= MAX_IDEMPOTENCY_KEY_LENGTH:
        raise ValidationError("invalid idempotency key")
    attributes = {f"{feature}.operation": operation}
    counter = f"sidekick.{feature}.operations"
    try:
        with telemetry.span(f"{feature}.operation", attributes):

            def write(session: TxSession) -> dict[str, Any]:
                record = store.idempotent(
                    session,
                    actor_id=actor_id,
                    operation=f"{feature}.{operation}",
                    key=key,
                    payload=payload,
                    execute=lambda: execute(session),
                    replay=replay,
                )
                return record if rebuild is None else rebuild(session, record)

            result = store.transaction(write)
    except Exception:
        telemetry.count(counter, {**attributes, "outcome": "failure"})
        raise
    telemetry.count(counter, {**attributes, "outcome": "success"})
    logger.info(
        f"{feature}_operation_completed",
        extra={"correlation_id": correlation_id, "operation": operation, "outcome": "success"},
    )
    return result
