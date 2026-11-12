"""MCP error results: a closed `reason` plus a fixed English advice sentence, never raw text."""

from datetime import UTC, datetime, timedelta
from typing import Any, get_args

import pytest
from fastmcp import Client
from fastmcp.client.client import CallToolResult
from fastmcp.tools import ToolResult
from mcp.types import TextContent

from sidekick.api.app import create_container
from sidekick.mcp.auth import current_actor
from sidekick.mcp.results import REASON_ADVICE, error_result
from sidekick.mcp.server import create_mcp_server
from sidekick.shared.errors import (
    AuthenticationRequiredError,
    ConflictError,
    InvalidInputError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.errors.core import SidekickErrorReason
from sidekick.shared.types import Actor, new_uuid7
from sidekick.tasks.domain.task import Priority, Task, TaskStatus
from tests.db import database_factory
from tests.support.settings import make_settings

SCOPES = frozenset({"projects:read", "projects:write", "tasks:read", "tasks:write"})
STALE_ADVICE = "Re-read the record and retry with its current version."
NOT_BEFORE_ADVICE = (
    "Set the earliest start no later than the due date, or change the due date as well."
)


def _structured(result: ToolResult | CallToolResult) -> dict[str, Any]:
    assert result.structured_content is not None
    return result.structured_content


def _text(result: ToolResult | CallToolResult) -> str:
    block = result.content[0]
    assert isinstance(block, TextContent)
    return block.text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_stale_version_on_update_task_gives_reason_and_advice() -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("error-owner", "Owner")
    server = create_mcp_server(
        container, actor_provider=lambda: Actor(owner, SCOPES), enable_auth=False
    )
    async with Client(server) as client:
        created = await client.call_tool(
            "create_task", {"title": "Stale task", "idempotency_key": "error-task-0001"}
        )
        task = _structured(created)["task"]
        updated = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "error-update-0001",
                "changes": {"title": "Fresh title"},
            },
        )
        assert not updated.is_error, updated.structured_content

        # The version from before the first update is now stale.
        stale = await client.call_tool(
            "update_task",
            {
                "task_id": task["id"],
                "version": task["version"],
                "idempotency_key": "error-update-0002",
                "changes": {"title": "Old view"},
            },
            raise_on_error=False,
        )

    assert stale.is_error
    stale_content = _structured(stale)
    assert stale_content["code"] == "conflict"
    assert stale_content["reason"] == "stale_version"
    # The spoken line names the task by its current title and says what to do; no id or version.
    assert _text(stale) == "Fresh title changed. Re-read the task and retry."


def test_stale_version_without_a_name_keeps_the_generic_advice() -> None:
    result = error_result(ConflictError("stale", reason="stale_version"))

    assert _text(result) == f"That changed in the meantime. {STALE_ADVICE}"


def test_stale_shopping_item_names_the_item_and_says_what_to_do() -> None:
    result = error_result(
        ConflictError(
            "stale", reason="stale_version", subject="Mjölk\n 1l", subject_kind="shopping_item"
        )
    )

    assert _text(result) == "Mjölk 1l changed (bought in the app?). Re-read the list and retry."
    assert _structured(result)["reason"] == "stale_version"


def test_not_before_after_due_gives_reason_and_advice_without_domain_text() -> None:
    result = error_result(
        ValidationError(
            "earliest start cannot be later than the due date",
            reason="not_before_after_due",
        )
    )

    assert result.is_error
    content = _structured(result)
    assert content["code"] == "validation_error"
    assert content["reason"] == "not_before_after_due"
    assert _text(result) == f"Request validation failed. {NOT_BEFORE_ADVICE}"


def test_unknown_error_gives_generic_message_and_no_reason() -> None:
    result = error_result(RuntimeError("secret detail from an upstream system"))

    assert result.is_error
    content = _structured(result)
    assert content["code"] == "internal_error"
    assert content["message"] == "Request failed."
    assert "reason" not in content
    assert _text(result) == "Request failed."


class _Replayed(Exception):
    """A stand-in for a SidekickError-like error whose closed code is idempotency_conflict."""

    code = "idempotency_conflict"


def test_plain_errors_say_what_happened_without_protocol_words() -> None:
    assert _text(error_result(PermissionDeniedError("private scope detail"))) == (
        "You do not have access to that."
    )
    assert _text(error_result(NotFoundError("private id detail"))) == (
        "I could not find that. Check the name or search again."
    )
    replayed = error_result(_Replayed("private key detail"))  # pyright: ignore[reportArgumentType]
    assert _text(replayed) == "That request key was already used with different data."
    assert _structured(replayed)["code"] == "idempotency_conflict"


def test_a_missing_scope_answers_forbidden_without_naming_the_scope() -> None:
    with pytest.raises(PermissionDeniedError) as refused:
        Actor(new_uuid7(), frozenset()).require("tasks:write")

    result = error_result(refused.value)
    assert _structured(result)["code"] == "forbidden"
    assert _text(result) == "You do not have access to that."
    assert "tasks:write" not in repr(result.structured_content)


def test_a_call_without_a_verified_identity_answers_unauthorized() -> None:
    with pytest.raises(AuthenticationRequiredError) as refused:
        current_actor()

    result = error_result(refused.value)
    assert _structured(result)["code"] == "unauthorized"
    assert _text(result) == "Authentication required."


@pytest.mark.asyncio
async def test_a_write_tool_without_a_verified_identity_answers_unauthorized() -> None:
    server = create_mcp_server(create_container(make_settings()), enable_auth=False)

    async with Client(server) as client:
        result = await client.call_tool(
            "create_task",
            {"title": "no identity", "idempotency_key": "no-identity-0001"},
            raise_on_error=False,
        )

    assert result.is_error
    assert _structured(result)["code"] == "unauthorized"


def test_every_reason_has_advice() -> None:
    assert set(get_args(SidekickErrorReason)) == set(REASON_ADVICE)


def test_a_task_starting_after_its_due_date_raises_with_its_reason() -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError) as raised:
        Task(
            id=new_uuid7(),
            owner_id=new_uuid7(),
            project_id=None,
            title="Ring Sara",
            description=None,
            status=TaskStatus.TODO,
            priority=Priority.NORMAL,
            due_at=now,
            completed_at=None,
            created_at=now,
            updated_at=now,
            not_before=now + timedelta(days=1),
        )

    assert raised.value.reason == "not_before_after_due"


def test_an_instrumented_failure_logs_its_class_with_the_reply_id() -> None:
    import logging
    from unittest.mock import MagicMock

    from sidekick.mcp.instrument import LOGGER, instrument_mcp

    records: list[logging.LogRecord] = []

    class _Collector(logging.Handler):
        def emit(self, record: logging.LogRecord) -> None:
            records.append(record)

    @instrument_mcp(MagicMock(), "probe_tool")
    def failing() -> ToolResult:
        raise RuntimeError("secret title text")

    handler = _Collector(level=logging.INFO)
    previous = LOGGER.level
    LOGGER.addHandler(handler)
    LOGGER.setLevel(logging.INFO)
    try:
        result = failing()
    finally:
        LOGGER.removeHandler(handler)
        LOGGER.setLevel(previous)

    assert isinstance(result, ToolResult)
    assert len(records) == 1
    fields = vars(records[0])
    assert fields["mcp_error_class"] == "RuntimeError"
    assert fields["correlation_id"] == _structured(result)["correlation_id"]
    assert "secret title text" not in repr(fields)


def test_only_a_rejected_client_value_is_a_validation_error() -> None:
    rejected = _structured(error_result(InvalidInputError("limit must be between 1 and 100")))
    assert rejected["code"] == "validation_error"
    assert "limit" not in rejected["message"]

    # A stray ValueError is a defect: it never passes for a client error, and its text stays out.
    defect = _structured(error_result(ValueError("select * from users where owner = 'anna'")))
    assert defect["code"] == "internal_error"
    assert "select" not in defect["message"].lower()
