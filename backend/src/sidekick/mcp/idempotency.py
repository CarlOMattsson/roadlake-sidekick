"""The one input type of every MCP tool's `idempotency_key`.

Its bounds are those the write path enforces (`run_idempotent_operation`), so a key the schema
accepts is a key the use case accepts, and one the schema refuses never reaches the database.
"""

from __future__ import annotations

from typing import Annotated

from pydantic import Field

from sidekick.shared.types import (
    MAX_IDEMPOTENCY_KEY_LENGTH,
    MIN_IDEMPOTENCY_KEY_LENGTH,
)

IdempotencyKey = Annotated[
    str, Field(min_length=MIN_IDEMPOTENCY_KEY_LENGTH, max_length=MAX_IDEMPOTENCY_KEY_LENGTH)
]
