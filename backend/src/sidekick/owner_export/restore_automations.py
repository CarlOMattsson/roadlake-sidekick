"""What a restore does with automations: it checks the references it rewrites and leaves the
approval and the work in progress of the old instance behind."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any, cast
from uuid import UUID

from sidekick.owner_export.catalogue import ExportRefused

# Run states that mean work is in progress; a restored run in one of them is cancelled, since no
# worker of the new instance holds it.
ACTIVE_AUTOMATION_RUN_STATES = frozenset({"queued", "running", "checking"})
# The id fields inside a suggestion's payload, by effect, and the collection each one points at. An
# effect whose payload names another record must be listed here; a test walks the effect catalogue
# and fails for an id field that is not.
PAYLOAD_REFERENCES: Mapping[str, Mapping[str, str]] = {
    "create_task": {"project_id": "projects"},
    "create_contact": {},
}
_UNFINISHED_SUGGESTION_STATES = frozenset({"received", "checking"})
_PAYLOAD_FIELDS = ("payload", "proposed_payload")

NewId = Callable[[UUID, str], UUID]
"""The stable id a record of the named collection gets in the target owner."""


def _parsed(value: Any) -> UUID | None:
    if not isinstance(value, str):
        return None
    try:
        return UUID(value)
    except ValueError:
        return None


def _payload_references(row: Mapping[str, Any]) -> list[tuple[str, Any]]:
    """The (field, value) pairs of a suggestion's payloads that hold an id."""

    fields = PAYLOAD_REFERENCES.get(str(row.get("effect")), {})
    found: list[tuple[str, Any]] = []
    for name in _PAYLOAD_FIELDS:
        payload = row.get(name)
        if isinstance(payload, Mapping):
            values = cast(Mapping[str, Any], payload)
            found.extend((f"{name}.{field}", values[field]) for field in fields if field in values)
    return found


def require_valid_references(suggestions: list[Mapping[str, Any]]) -> None:
    """Refuse a suggestion whose datapoint or payload ids are not ids.

    A restore rewrites them, so a value that cannot be read as an id would otherwise fail in the
    middle of the write. The refusal names the row position and field, never content.
    """

    for position, row in enumerate(suggestions):
        datapoints = row.get("datapoint_ids")
        if not isinstance(datapoints, list) or any(
            _parsed(item) is None for item in cast(list[Any], datapoints)
        ):
            raise ExportRefused(
                f"export has an invalid reference: automation_suggestions[{position}]: "
                "datapoint_ids"
            )
        for field, value in _payload_references(row):
            if value is not None and _parsed(value) is None:
                raise ExportRefused(
                    f"export has an invalid reference: automation_suggestions[{position}]: {field}"
                )


def restore_warnings(
    automations: list[Mapping[str, Any]], runs: list[Mapping[str, Any]]
) -> tuple[str, ...]:
    """Warnings for what a restore leaves out of automations; they hold counts, never content."""

    found: list[str] = []
    approved = sum(1 for row in automations if row.get("approved_digest") is not None)
    if approved:
        found.append(
            f"{approved} approved automation(s) are not restored as approved; approve them again "
            "on the new instance."
        )
    active = sum(1 for run in runs if run.get("state") in ACTIVE_AUTOMATION_RUN_STATES)
    if active:
        found.append(f"{active} queued or running automation run(s) are restored as cancelled.")
    return tuple(found)


def apply_restore_rules(remapped: Mapping[str, list[dict[str, Any]]], new_id: NewId) -> None:
    """Drop what a restored record must not carry over from the instance it was exported from.

    An automation is restored without its approval: the owner approved it for the instance it ran
    on, and two instances must not run the same definition on that one approval. A run that was
    queued, running or checking is restored as cancelled with no lease, worker or reservation. A
    suggestion that was still being screened or checked (`received` or `checking`) has nothing on
    the new instance that would finish it, so it is shown as pending with a failed check, the way
    a check that gave no usable answer leaves it. The ids a suggestion holds (its datapoints and
    the project in a task payload) follow the records they name, which keep their stable ids
    whether or not the record is in the export.
    """

    for automation in remapped["automations"]:
        automation["approved_digest"] = None
        automation["approved_at"] = None
    for run in remapped["automation_runs"]:
        if run.get("state") in ACTIVE_AUTOMATION_RUN_STATES:
            run["state"] = "cancelled"
            run["lease_until"] = None
            run["worker_id"] = None
            run["reserved_microusd"] = 0
            run["finished_at"] = run.get("finished_at") or run["updated_at"]
    for suggestion in remapped["automation_suggestions"]:
        _remap_suggestion_references(suggestion, new_id)
        if suggestion.get("state") in _UNFINISHED_SUGGESTION_STATES:
            suggestion["state"] = "pending"
            suggestion["check_state"] = "failed"


def _remap_suggestion_references(suggestion: dict[str, Any], new_id: NewId) -> None:
    suggestion["datapoint_ids"] = [
        new_id(UUID(str(item)), "automation_datapoints") for item in suggestion["datapoint_ids"]
    ]
    fields = PAYLOAD_REFERENCES.get(str(suggestion.get("effect")), {})
    for name in _PAYLOAD_FIELDS:
        payload = suggestion.get(name)
        if not isinstance(payload, Mapping):
            continue
        values = dict(cast(Mapping[str, Any], payload))
        for field, collection in fields.items():
            if values.get(field) is not None:
                values[field] = str(new_id(UUID(str(values[field])), collection))
        suggestion[name] = values
