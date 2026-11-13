"""Owner review of an AI-derived Journal draft through the four MCP review tools."""

import logging
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from datetime import date
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastmcp import Client
from sqlalchemy import text

from sidekick.api.app import Container, create_container
from sidekick.journal.domain.source import SourceType
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support.journal_drafts import seed_entry_draft
from tests.support.mcp_journal_review import (
    call,
    finalize_args,
    read_draft,
    update_args,
)
from tests.support.settings import make_settings

SOURCE_TEXT = "sentinel-draft-source-text-5b2d"
TASK_TITLE = "sentinel-catalog-task-label-77ac"
OWNER_SCOPES = frozenset(
    {
        "journal:read",
        "journal:write",
        "projects:read",
        "tasks:read",
        "tasks:write",
        "contacts:read",
    }
)
READ_ONLY = frozenset({"journal:read"})
WRITE_ONLY = frozenset({"journal:write"})
REVIEW_TOOLS = (
    "update_journal_draft",
    "reject_journal_draft",
    "finalize_journal_draft",
)


@dataclass(frozen=True, slots=True)
class Harness:
    container: Container
    actor: Actor
    draft_id: UUID
    task_id: UUID
    source_id: UUID
    mcp: SwitchableServer

    def client(self, scopes: frozenset[str] = OWNER_SCOPES, user_id: UUID | None = None) -> Client:
        return self.mcp.client(Actor(user_id or self.actor.user_id, scopes))


async def make_harness(username: str, *, with_task: bool = True) -> Harness:
    container = create_container(make_settings(), database_factory())
    user_id = container.auth.provision_user(username, "Review Owner")
    actor = Actor(user_id, OWNER_SCOPES)
    task_id = uuid4()
    if with_task:
        task_id = container.tasks.create(
            actor, title=TASK_TITLE, idempotency_key=f"{username}-task"
        ).id
    source = container.journal_capture.create_source(
        actor,
        source_type=SourceType.MANUAL_TEXT,
        journal_date=date(2026, 7, 21),
        occurred_at=None,
        source_recorded_at=None,
        raw_text=SOURCE_TEXT,
        language="sv",
        replaces_source_id=None,
        idempotency_key=f"{username}-source",
    )
    draft_id = seed_entry_draft(container, actor, source.id, source.journal_date)
    return Harness(
        container,
        actor,
        draft_id,
        task_id,
        source.id,
        SwitchableServer.build(container, actor),
    )


def count(container: Container, table: str, owner_id: UUID) -> int:
    with container.session_factory() as session:
        return session.execute(
            text(f"SELECT count(*) FROM sidekick.{table} WHERE owner_id = :owner"),
            {"owner": owner_id},
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_draft_withholds_all_text_only_when_include_content_is_false() -> None:
    harness = await make_harness("review-gating-owner")
    async with harness.client() as client:
        plain = await read_draft(client, harness.draft_id, content=False)
        draft = plain["draft"]
        assert draft["state"] == "pending_review" and draft["version"] == 1
        assert draft["title"]
        assert draft["summary"] is None and draft["key_points"] == []
        assert draft["task_proposals"] == [] and draft["task_proposal_count"] == 1
        assert draft["catalog"] == {"projects": [], "tasks": [], "contacts": []}
        assert all(
            item["rationale"] is None for kind in draft["suggestions"].values() for item in kind
        )
        assert draft["suggestions"]["tasks"][0]["id"] == str(harness.task_id)
        assert plain["source"]["id"] == str(harness.source_id)
        assert plain["source"]["raw_text"] is None
        assert SOURCE_TEXT not in str(plain) and TASK_TITLE not in str(plain)
        assert draft["run"]["provider"] == "fake"

        full = await read_draft(client, harness.draft_id)
        assert full["draft"]["summary"]
        assert full["draft"]["key_points"]
        assert full["draft"]["suggestions"]["tasks"][0]["rationale"]
        assert full["draft"]["catalog"]["tasks"][0]["label"] == TASK_TITLE
        assert full["source"]["raw_text"] == SOURCE_TEXT
        proposal = full["draft"]["task_proposals"][0]
        # Presence is preserved: a field the model never set stays absent, not null.
        assert proposal["type"] == "update_task" and proposal["task_id"] == str(harness.task_id)
        assert "due_at" in proposal and "description" not in proposal and "title" not in proposal


@pytest.mark.asyncio
@pytest.mark.integration
async def test_get_draft_returns_its_text_without_any_content_argument() -> None:
    harness = await make_harness("review-default-owner")
    async with harness.client() as client:
        response = await call(client, "get_journal_draft", {"draft_id": str(harness.draft_id)})
    assert not response.is_error, response.structured_content
    draft = response.structured_content["draft"]
    assert draft["summary"] and draft["key_points"]
    assert response.structured_content["source"]["raw_text"] == SOURCE_TEXT
    # Block 2 is the full structured result (D-060), so the host model reads the draft text.
    assert SOURCE_TEXT in response.content[1].text


@pytest.mark.asyncio
@pytest.mark.integration
async def test_draft_content_is_limited_to_the_read_scopes_of_the_records_it_describes() -> None:
    harness = await make_harness("review-scoped-owner")
    task_only = frozenset({"journal:read", "tasks:read"})

    async with harness.client(scopes=READ_ONLY) as client:
        narrow = await read_draft(client, harness.draft_id)
    draft = narrow["draft"]
    assert TASK_TITLE not in str(narrow)
    assert draft["catalog"] == {"projects": [], "tasks": [], "contacts": []}
    assert draft["task_proposals"] == [] and draft["task_proposal_count"] == 1
    assert draft["suggestions"] == {"projects": [], "tasks": [], "contacts": []}
    # The journal's own text is still available to journal:read.
    assert draft["summary"] and narrow["source"]["raw_text"] == SOURCE_TEXT

    async with harness.client(scopes=task_only) as client:
        tasks = await read_draft(client, harness.draft_id)
    assert tasks["draft"]["catalog"]["tasks"][0]["label"] == TASK_TITLE
    assert tasks["draft"]["catalog"]["projects"] == []
    assert tasks["draft"]["task_proposals"][0]["task_id"] == str(harness.task_id)
    assert tasks["draft"]["suggestions"]["tasks"][0]["rationale"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_another_owners_draft_is_not_found_for_every_review_tool() -> None:
    harness = await make_harness("review-scope-owner")
    other_id = harness.container.auth.provision_user("review-scope-other", "Other")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)

    builders: dict[str, Callable[[str], dict[str, Any]]] = {
        "get_journal_draft": lambda target: {"draft_id": target, "include_content": True},
        "update_journal_draft": lambda target: update_args(
            owned, "review-other-update", draft_id=target
        ),
        "reject_journal_draft": lambda target: {
            "draft_id": target,
            "expected_version": 1,
            "idempotency_key": "review-other-reject",
        },
        "finalize_journal_draft": lambda target: finalize_args(
            owned, "review-other-finalize", draft_id=target
        ),
    }
    async with harness.client(user_id=other_id) as client:
        for tool, build in builders.items():
            foreign = await call(client, tool, build(str(harness.draft_id)))
            absent = await call(client, tool, build(str(uuid4())))
            assert foreign.is_error and absent.is_error, tool
            assert foreign.structured_content["code"] == "not_found", tool
            assert foreign.structured_content["message"] == absent.structured_content["message"]
            assert SOURCE_TEXT not in str(foreign.structured_content)

    async with harness.client() as client:
        unchanged = await read_draft(client, harness.draft_id)
    assert unchanged["draft"]["state"] == "pending_review" and unchanged["draft"]["version"] == 1
    assert count(harness.container, "journal_entries", harness.actor.user_id) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_tools_are_forbidden_without_their_scope_and_change_nothing() -> None:
    harness = await make_harness("review-forbidden-owner")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)

    async with harness.client(scopes=WRITE_ONLY) as client:
        denied = await call(client, "get_journal_draft", {"draft_id": str(harness.draft_id)})
        assert denied.is_error and denied.structured_content["code"] == "forbidden"

    async with harness.client(scopes=READ_ONLY) as client:
        attempts = {
            "update_journal_draft": update_args(owned, "review-forbidden-update"),
            "reject_journal_draft": {
                "draft_id": str(harness.draft_id),
                "expected_version": 1,
                "idempotency_key": "review-forbidden-reject",
            },
            "finalize_journal_draft": finalize_args(owned, "review-forbidden-finalize"),
        }
        for tool, arguments in attempts.items():
            denied = await call(client, tool, arguments)
            assert denied.is_error, tool
            assert denied.structured_content["code"] == "forbidden", tool

    # Finalizing a Task proposal also needs tasks:write; journal:write alone is not enough.
    async with harness.client(scopes=WRITE_ONLY) as client:
        denied = await call(
            client, "finalize_journal_draft", finalize_args(owned, "review-forbidden-tasks")
        )
        assert denied.is_error and denied.structured_content["code"] == "forbidden"

    async with harness.client() as client:
        unchanged = await read_draft(client, harness.draft_id)
    assert unchanged["draft"]["state"] == "pending_review" and unchanged["draft"]["version"] == 1
    assert count(harness.container, "journal_entries", harness.actor.user_id) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_update_is_versioned_idempotent_and_preserves_explicit_null() -> None:
    harness = await make_harness("review-update-owner")
    async with harness.client() as client:
        first_read = await read_draft(client, harness.draft_id)
        proposals = first_read["draft"]["task_proposals"]
        proposals[0]["description"] = None  # an explicit null, distinct from an omitted field
        arguments = update_args(first_read, "review-update-1", task_proposals=proposals)

        updated = await call(client, "update_journal_draft", arguments)
        assert not updated.is_error, updated.structured_content
        status = updated.structured_content["draft"]
        assert status["version"] == 2 and status["state"] == "pending_review"
        assert status["title"] == "Granskad titel" and status["task_proposal_count"] == 1
        # The edit result echoes no draft text.
        assert "Granskad sammanfattning" not in str(updated.structured_content)

        replay = await call(client, "update_journal_draft", arguments)
        assert replay.structured_content == updated.structured_content

        changed = await call(
            client, "update_journal_draft", {**arguments, "title": "Annan nyttolast"}
        )
        assert changed.is_error
        assert changed.structured_content["code"] == "conflict"

        stale = await call(
            client, "update_journal_draft", {**arguments, "idempotency_key": "review-update-2"}
        )
        assert stale.is_error and stale.structured_content["code"] == "conflict"

        reread = await read_draft(client, harness.draft_id)
        assert reread["draft"]["version"] == 2
        assert reread["draft"]["title"] == "Granskad titel"
        assert reread["draft"]["summary"] == "Granskad sammanfattning."
        stored = reread["draft"]["task_proposals"][0]
        assert stored["description"] is None and "title" not in stored

        # A proposal the draft's immutable snapshot does not contain is refused.
        unknown = dict(proposals[0], task_id=str(uuid4()))
        refused = await call(
            client,
            "update_journal_draft",
            update_args(reread, "review-update-3", task_proposals=[unknown]),
        )
        assert refused.is_error and refused.structured_content["code"] == "validation_error"
        assert (await read_draft(client, harness.draft_id))["draft"]["version"] == 2

        blank = await call(
            client,
            "update_journal_draft",
            update_args(reread, "review-update-blank", title="   "),
        )
        # Blank after trimming is refused by the use case, as on REST; nothing is stored.
        assert blank.is_error, blank.structured_content
        assert blank.structured_content["code"] == "validation_error"
        blank_final = await call(
            client,
            "finalize_journal_draft",
            finalize_args(reread, "review-update-blank-final", title="   "),
        )
        assert blank_final.is_error and blank_final.structured_content["code"] == "validation_error"
        assert (await read_draft(client, harness.draft_id))["draft"]["version"] == 2

        invalid = await client.call_tool(
            "update_journal_draft",
            {**arguments, "idempotency_key": "review-update-4", "expected_version": 0},
            raise_on_error=False,
        )
        assert invalid.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_reject_is_terminal_idempotent_and_blocks_every_later_change() -> None:
    harness = await make_harness("review-reject-owner")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        reject = {
            "draft_id": str(harness.draft_id),
            "expected_version": 1,
            "idempotency_key": "review-reject-1",
        }
        stale = await call(client, "reject_journal_draft", {**reject, "expected_version": 5})
        assert stale.is_error and stale.structured_content["code"] == "conflict"

        rejected = await call(client, "reject_journal_draft", reject)
        assert not rejected.is_error, rejected.structured_content
        assert rejected.structured_content["draft"]["state"] == "rejected"
        assert rejected.structured_content["draft"]["version"] == 2
        assert SOURCE_TEXT not in str(rejected.structured_content)
        assert (await call(client, "reject_journal_draft", reject)).structured_content == (
            rejected.structured_content
        )

        later = {
            "update_journal_draft": update_args(owned, "review-reject-update", expected_version=2),
            "reject_journal_draft": {
                **reject,
                "expected_version": 2,
                "idempotency_key": "review-reject-again",
            },
            "finalize_journal_draft": finalize_args(
                owned, "review-reject-finalize", expected_version=2
            ),
        }
        for tool, arguments in later.items():
            blocked = await call(client, tool, arguments)
            assert blocked.is_error, tool
            assert blocked.structured_content["code"] == "conflict", tool

        reread = await read_draft(client, harness.draft_id, content=False)
        assert reread["draft"]["state"] == "rejected" and reread["draft"]["version"] == 2
    assert count(harness.container, "journal_entries", harness.actor.user_id) == 0
    # The preserved source is still readable after the draft is rejected.
    async with harness.client() as client:
        source = await client.call_tool("get_journal_source", {"source_id": str(harness.source_id)})
        assert source.structured_content["source"]["id"] == str(harness.source_id)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finalize_creates_one_entry_applies_kept_proposals_and_is_terminal() -> None:
    harness = await make_harness("review-finalize-owner")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        arguments = finalize_args(
            owned,
            "review-finalize-1",
            relation_selection={
                "project_ids": [],
                "task_ids": [{"id": str(harness.task_id), "origin": "model_suggested"}],
                "contact_ids": [],
            },
        )

        stale = await call(client, "finalize_journal_draft", {**arguments, "expected_version": 3})
        assert stale.is_error and stale.structured_content["code"] == "conflict"

        finalized = await call(client, "finalize_journal_draft", arguments)
        assert not finalized.is_error, finalized.structured_content
        entry = finalized.structured_content["entry"]
        assert entry["title"] == "Granskad titel" and entry["version"] == 1
        assert entry["source_id"] == str(harness.source_id)
        assert entry["task_ids"] == [str(harness.task_id)]
        assert finalized.structured_content["updated_task_ids"] == [str(harness.task_id)]
        assert finalized.structured_content["created_task_ids"] == []

        replay = await call(client, "finalize_journal_draft", arguments)
        assert replay.structured_content == finalized.structured_content
        changed = await call(
            client, "finalize_journal_draft", {**arguments, "title": "Annan nyttolast"}
        )
        assert changed.is_error and changed.structured_content["code"] == "conflict"

        for tool, later in {
            "update_journal_draft": update_args(owned, "review-final-update", expected_version=2),
            "reject_journal_draft": {
                "draft_id": str(harness.draft_id),
                "expected_version": 2,
                "idempotency_key": "review-final-reject",
            },
            "finalize_journal_draft": {**arguments, "idempotency_key": "review-final-again"},
        }.items():
            blocked = await call(client, tool, later)
            assert blocked.is_error, tool
            assert blocked.structured_content["code"] == "conflict", tool

        read_back = await client.call_tool(
            "get_journal_entry", {"entry_id": entry["id"], "include_content": True}
        )
        assert read_back.structured_content["entry"]["summary"] == "Granskad sammanfattning."
        reread = await read_draft(client, harness.draft_id, content=False)
        assert reread["draft"]["state"] == "finalized"

    assert count(harness.container, "journal_entries", harness.actor.user_id) == 1
    with harness.container.session_factory() as session:
        assert session.execute(
            text("SELECT due_at IS NOT NULL FROM sidekick.tasks WHERE id = :id"),
            {"id": harness.task_id},
        ).scalar_one()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finalize_can_tag_the_entry_and_a_replay_does_not_tag_twice() -> None:
    harness = await make_harness("review-finalize-tags")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        arguments = finalize_args(owned, "review-finalize-tags-1", tags=["Viktig", "familj"])

        finalized = await call(client, "finalize_journal_draft", arguments)

        assert not finalized.is_error, finalized.structured_content
        entry = finalized.structured_content["entry"]
        assert sorted(entry["tags"]) == ["familj", "viktig"]
        replay = await call(client, "finalize_journal_draft", arguments)
        assert replay.structured_content == finalized.structured_content
        read_back = await client.call_tool(
            "get_journal_entry", {"entry_id": entry["id"], "include_content": False}
        )
        assert sorted(read_back.structured_content["entry"]["tags"]) == ["familj", "viktig"]
        # The same payload without tags is a different request, not a replay.
        untagged = await call(
            client,
            "finalize_journal_draft",
            {key: value for key, value in arguments.items() if key != "tags"},
        )
        assert untagged.is_error and untagged.structured_content["code"] == "conflict"
    assert count(harness.container, "journal_entry_tags", harness.actor.user_id) == 2


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finalize_refuses_too_many_tags_and_writes_nothing() -> None:
    harness = await make_harness("review-finalize-many-tags")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        arguments = finalize_args(
            owned, "review-finalize-many-1", tags=[f"tagg{n}" for n in range(11)]
        )

        refused = await call(client, "finalize_journal_draft", arguments)

        assert refused.is_error
    assert count(harness.container, "journal_entries", harness.actor.user_id) == 0
    assert count(harness.container, "work_tags", harness.actor.user_id) == 0


@pytest.mark.asyncio
@pytest.mark.integration
async def test_finalize_refuses_unknown_relations_and_unkept_snapshot_escapes() -> None:
    harness = await make_harness("review-relations-owner")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        outside_snapshot = finalize_args(
            owned,
            "review-relations-1",
            relation_selection={
                "project_ids": [{"id": str(uuid4()), "origin": "model_suggested"}],
                "task_ids": [],
                "contact_ids": [],
            },
        )
        refused = await call(client, "finalize_journal_draft", outside_snapshot)
        assert refused.is_error and refused.structured_content["code"] == "validation_error"

        unknown_target = finalize_args(
            owned,
            "review-relations-2",
            relation_selection={
                "project_ids": [],
                "task_ids": [{"id": str(uuid4()), "origin": "user_selected"}],
                "contact_ids": [],
            },
        )
        missing = await call(client, "finalize_journal_draft", unknown_target)
        assert missing.is_error and missing.structured_content["code"] == "not_found"

        duplicated = finalize_args(
            owned,
            "review-relations-3",
            relation_selection={
                "project_ids": [],
                "task_ids": [
                    {"id": str(harness.task_id), "origin": "model_suggested"},
                    {"id": str(harness.task_id), "origin": "model_suggested"},
                ],
                "contact_ids": [],
            },
        )
        assert (await call(client, "finalize_journal_draft", duplicated)).is_error

        # Dropping the Task proposal finalizes without touching the Task.
        kept_none = await call(
            client,
            "finalize_journal_draft",
            finalize_args(owned, "review-relations-4", task_proposals=[]),
        )
        assert not kept_none.is_error, kept_none.structured_content
        assert kept_none.structured_content["updated_task_ids"] == []
    assert count(harness.container, "journal_entries", harness.actor.user_id) == 1
    with harness.container.session_factory() as session:
        assert session.execute(
            text("SELECT due_at IS NULL FROM sidekick.tasks WHERE id = :id"),
            {"id": harness.task_id},
        ).scalar_one()


class _Collector(logging.Handler):
    """Keeps every record that reaches it, whatever the propagation flags say."""

    def __init__(self) -> None:
        super().__init__(logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        formatter = logging.Formatter("%(levelname)s %(name)s %(message)s")
        parts = [formatter.format(record) for record in self.records]
        parts.extend(repr(record.__dict__) for record in self.records)
        return "\n".join(parts)


@pytest.fixture(name="all_logs")
def _all_logs() -> Iterator[_Collector]:
    """Attach to root and to every logger, as test_tool_argument_logging does."""

    collector = _Collector()
    loggers: list[logging.Logger] = [logging.getLogger()]
    loggers.extend(
        item
        for item in logging.root.manager.loggerDict.values()
        if isinstance(item, logging.Logger)
    )
    for logger in loggers:
        logger.addHandler(collector)
    try:
        yield collector
    finally:
        for logger in loggers:
            logger.removeHandler(collector)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_review_tools_never_write_draft_or_source_text_to_a_log(
    all_logs: _Collector,
) -> None:
    title_sentinel = "sentinel-edited-title-31fe"
    summary_sentinel = "sentinel-edited-summary-8d0a"
    harness = await make_harness("review-log-owner")
    async with harness.client() as client:
        owned = await read_draft(client, harness.draft_id)
        edit = update_args(
            owned, "review-log-update", title=title_sentinel, summary=summary_sentinel
        )
        await call(client, "update_journal_draft", edit)
        # Schema-valid but rejected by pydantic: FastMCP logs the input on this path.
        await call(client, "update_journal_draft", {**edit, "draft_id": summary_sentinel})
        await call(client, "update_journal_draft", {**edit, "draft_id": str(uuid4())})
        await call(
            client,
            "finalize_journal_draft",
            finalize_args(
                owned,
                "review-log-finalize",
                expected_version=2,
                title=title_sentinel,
                summary=summary_sentinel,
            ),
        )
        await call(
            client,
            "reject_journal_draft",
            {
                "draft_id": str(harness.draft_id),
                "expected_version": 3,
                "idempotency_key": "review-log-reject",
            },
        )

    rendered = all_logs.rendered()
    # The pydantic-failure path above really logged, and logged without its content.
    assert "fastmcp tool warning record (content withheld)" in rendered
    for sentinel in (SOURCE_TEXT, TASK_TITLE, title_sentinel, summary_sentinel):
        assert sentinel not in rendered, sentinel
    assert all(not record.args for record in all_logs.records)
    assert all(record.exc_info is None for record in all_logs.records)
