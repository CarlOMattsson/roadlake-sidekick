"""What a restore does with ready conversations: it refuses one whose cadence cannot be read or
whose instruction does not say who wrote it.

The table's CHECKs hold the closed values (kind, state, ingredients) but a cadence is only known to
be a JSON object there, so a restored row with a malformed one would later fail every read of the
conversation. An instruction always carries who wrote it (`you` or `claude`) and whether the model
edited it, since that decides whether it is shown as verified; a row that disagrees with itself
would be refused by the table in the middle of a restore. The refusals come with the plan and name
the row position, never content.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from pydantic import ValidationError as ModelValidationError

from sidekick.automations.domain.spec import Cadence
from sidekick.owner_export.catalogue import ExportRefused


def require_readable_cadences(conversations: list[Mapping[str, Any]]) -> None:
    """Refuse a ready conversation whose cadence is not a valid recurrence and time of day."""

    for position, row in enumerate(conversations):
        try:
            Cadence.model_validate(row.get("cadence"))
        except ModelValidationError:
            raise ExportRefused(
                "export has a ready conversation with an unreadable cadence: "
                f"ready_conversations[{position}]"
            ) from None


_WRITERS = frozenset({"you", "claude"})


def require_consistent_provenance(conversations: list[Mapping[str, Any]]) -> None:
    """Refuse a conversation whose instruction and its writer disagree: a text needs `you` or
    `claude`, and no text means no writer and no model edit."""

    for position, row in enumerate(conversations):
        written_by = row.get("instruction_written_by")
        edited = row.get("instruction_edited_by_model")
        has_text = row.get("instruction") is not None
        consistent = isinstance(edited, bool) and (
            written_by in _WRITERS if has_text else written_by is None and not edited
        )
        if not consistent:
            raise ExportRefused(
                "export has a ready conversation whose instruction and its writer disagree: "
                f"ready_conversations[{position}]"
            )
