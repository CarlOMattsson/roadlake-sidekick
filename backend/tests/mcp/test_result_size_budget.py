"""Result size budget for the list and board tools at their maximal limit.

Claude takes about 150 000 characters per tool result. The budget here is 100 000 for ordinary data,
which leaves room for the rest of a turn; with every title at its longest length (200) the result
must still stay under the 150 000 limit itself. Free text at its longest length (10 000) must too:
the list tools return a description excerpt of about 160 characters, not the whole description.
Each measured result counts the characters of its text blocks plus the JSON of its
structuredContent, the same measure the model is charged for. The fixture fills
every list past its limit so that each call returns a full page.

Each tool is its own test case, so xdist can spread them. The fixture is written in one
transaction with the store's row mappers, not through the create tools: those cost a transaction,
an idempotency record and an audit event per record, and nothing here measures them.
"""

import json
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any
from uuid import UUID

import pytest
from fastmcp import Client, FastMCP
from mcp.types import TextContent

from sidekick.api.app import Container, create_container
from sidekick.contacts.domain.contact import Contact
from sidekick.contacts.domain.normalization import normalize_name
from sidekick.mcp.server import create_mcp_server
from sidekick.mcp.text import BOARD_ROW_LIMIT
from sidekick.projects.domain.project import Project, ProjectStatus
from sidekick.shared.types import Actor, new_uuid7
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.domain.task import Priority, Task, TaskStatus
from sidekick.work.domain.context import Domain, DomainStatus
from sidekick.work.domain.steps import Step
from tests.db import database_factory
from tests.support.settings import make_settings

BUDGET = 100_000
READ_SCOPES = frozenset({"projects:read", "tasks:read", "contacts:read"})
PROJECT_COUNT = 100
TASKS_PER_PROJECT = 2
CONTACT_COUNT = 100
STEPPED_TASKS = 20
# The longest values the write tools accept: a title or name of 200 characters, free text of 10 000.
# Data measured only on short strings would prove nothing: real data can be this long.
MAX_TITLE = 200
MAX_TEXT = 10_000
# What Claude takes per tool result. Past it the result is cut or refused, whatever the budget above
# says, so it is the hard limit for the worst-case data below.
CLIENT_LIMIT = 150_000


def _server_for(container: Container, actor: Actor) -> FastMCP:
    return create_mcp_server(container, actor_provider=lambda: actor, enable_auth=False)


def _structured(tool_result: Any) -> dict[str, Any]:
    assert tool_result.structured_content is not None
    structured: dict[str, Any] = tool_result.structured_content
    return structured


def _measured_size(tool_result: Any) -> int:
    """Characters of the text blocks plus the JSON of structuredContent."""
    text = "".join(block.text for block in tool_result.content if isinstance(block, TextContent))
    return len(text) + len(json.dumps(tool_result.structured_content))


def _longest(prefix: str, length: int) -> str:
    """`prefix` padded with filler to exactly `length` characters."""
    return (prefix + " " + "x" * length)[:length]


def _title(prefix: str, length: int) -> str:
    return _longest(prefix, length) if length else prefix


def _text(length: int) -> str | None:
    return _longest("Fri text", length) if length else None


def _seed(container: Container, owner: UUID, title_length: int = 0, text_length: int = 0) -> None:
    """One Domain with 100 Projects, two Tasks per Project, two Steps on the first 20 Tasks,
    and 100 Contacts. The Hierarchy page then holds 100 nodes and at least 100 Tasks sit in it.
    Titles and names are short by default, or padded to `title_length`; the free text (descriptions,
    notes) is empty by default, or padded to `text_length`.

    One transaction, so the fixture costs one commit however many records it writes.
    """

    now = datetime.now(UTC)
    domain = Domain(
        id=new_uuid7(),
        owner_id=owner,
        name=_title("Storlek", title_length),
        description=_text(text_length),
        status=DomainStatus.ACTIVE,
        created_at=now,
        updated_at=now,
    )
    task_ids: list[UUID] = []
    with container.session_factory.begin() as session:
        SqlAlchemyStore.save_domain(session, domain)
        for project_index in range(PROJECT_COUNT):
            project = Project(
                id=new_uuid7(),
                owner_id=owner,
                title=_title(f"Storleksprojekt {project_index:03d}", title_length),
                description=_text(text_length),
                status=ProjectStatus.ACTIVE,
                start_date=None,
                target_date=None,
                domain_id=domain.id,
                created_at=now,
                updated_at=now,
            )
            SqlAlchemyStore.save_project(session, project)
            for task_index in range(TASKS_PER_PROJECT):
                task = Task(
                    id=new_uuid7(),
                    owner_id=owner,
                    project_id=project.id,
                    title=_title(
                        f"Storleksuppgift {project_index:03d}-{task_index} med en titel",
                        title_length,
                    ),
                    description=_text(text_length),
                    status=TaskStatus.TODO,
                    priority=Priority.NORMAL,
                    due_at=None,
                    completed_at=None,
                    created_at=now,
                    updated_at=now,
                )
                SqlAlchemyStore.save_task(session, task)
                SqlAlchemyStore.append_task_status_history(
                    session,
                    owner_id=owner,
                    task_id=task.id,
                    from_status=None,
                    to_status=TaskStatus.TODO,
                    changed_at=now,
                    source="created",
                )
                task_ids.append(task.id)
        for task_id in task_ids[:STEPPED_TASKS]:
            for step_index in range(2):
                SqlAlchemyStore.save_step(
                    session,
                    Step(
                        id=new_uuid7(),
                        owner_id=owner,
                        task_id=task_id,
                        title=_title(f"Steg {step_index + 1}", title_length),
                        status=TaskStatus.TODO,
                        position=step_index,
                        due_at=None,
                        attention_requested=False,
                        created_at=now,
                        updated_at=now,
                    ),
                )
        for contact_index in range(CONTACT_COUNT):
            display_name, display_name_key = normalize_name(
                _title(f"Storleskontakt {contact_index:03d}", title_length)
            )
            SqlAlchemyStore.save_contact(
                session,
                Contact(
                    id=new_uuid7(),
                    owner_id=owner,
                    display_name=display_name,
                    display_name_key=display_name_key,
                    context_note=_text(text_length),
                    email=None,
                    email_key=None,
                    phone=None,
                    phone_key=None,
                    aliases=[],
                    archived=False,
                    created_at=now,
                    updated_at=now,
                    archived_at=None,
                ),
            )


def _check_board(board: Any) -> None:
    # A budget measured on short pages would prove nothing, so every page must be full.
    board_items = sum(len(items) for items in _structured(board)["columns"].values())
    assert board_items == 100
    # The card's text names at most BOARD_ROW_LIMIT ids per section, however full the board is.
    # Each column lists its first Tasks and counts the rest; every other kind shares one section.
    assert len(board.content) == 1
    board_text = board.content[0].text
    board_rows = [line for line in board_text.splitlines() if line.startswith("- ")]
    columns = _structured(board)["columns"]
    sections = [
        [item for item in items if item.get("kind", "task") == "task"] for items in columns.values()
    ]
    sections.append(
        [item for items in columns.values() for item in items if item.get("kind", "task") != "task"]
    )
    assert len(board_rows) == sum(min(len(items), BOARD_ROW_LIMIT) for items in sections)
    for items in sections:
        if len(items) > BOARD_ROW_LIMIT:
            assert f"… {len(items) - BOARD_ROW_LIMIT} more" in board_text
    # Worst case: five sections of eight rows, each row an id, a kind, an 80-character title and
    # separators.
    assert len(board_text) < 5 * (BOARD_ROW_LIMIT * 132 + 40) + 300


def _check_tasks(tasks: Any) -> None:
    assert len(_structured(tasks)["tasks"]) == 100


def _check_contacts(contacts: Any) -> None:
    assert len(_structured(contacts)["contacts"]) == 100


def _check_projects(projects: Any) -> None:
    assert len(_structured(projects)["projects"]) == 100


def _check_hierarchy(hierarchy: Any) -> None:
    assert len(_structured(hierarchy)["nodes"]) == 100
    assert _structured(hierarchy)["tasks"]


@pytest.mark.asyncio
@pytest.mark.integration
@pytest.mark.parametrize(
    ("tool", "arguments", "check", "title_length", "text_length", "limit"),
    [
        # Ordinary data, against the budget that leaves room for the rest of a turn.
        pytest.param(
            "get_work_board",
            {"limit": 100},
            _check_board,
            0,
            0,
            BUDGET,
            id="board",
        ),
        pytest.param(
            "list_tasks",
            {"limit": 100},
            _check_tasks,
            0,
            0,
            BUDGET,
            id="tasks",
        ),
        pytest.param(
            "list_contacts",
            {"limit": 100},
            _check_contacts,
            0,
            0,
            BUDGET,
            id="contacts",
        ),
        pytest.param(
            "list_projects",
            {"limit": 100},
            _check_projects,
            0,
            0,
            BUDGET,
            id="projects",
        ),
        pytest.param(
            "get_work_hierarchy",
            {"limit": 100, "include_tasks": True},
            _check_hierarchy,
            0,
            0,
            BUDGET,
            id="hierarchy",
        ),
        # Every title at its longest length, against the client's own limit.
        pytest.param(
            "get_work_board",
            {"limit": 100},
            _check_board,
            MAX_TITLE,
            0,
            CLIENT_LIMIT,
            id="board-longest-titles",
        ),
        pytest.param(
            "list_tasks",
            {"limit": 100},
            _check_tasks,
            MAX_TITLE,
            0,
            CLIENT_LIMIT,
            id="tasks-longest-titles",
        ),
        pytest.param(
            "list_contacts",
            {"limit": 100},
            _check_contacts,
            MAX_TITLE,
            0,
            CLIENT_LIMIT,
            id="contacts-longest-titles",
        ),
        pytest.param(
            "list_projects",
            {"limit": 100},
            _check_projects,
            MAX_TITLE,
            0,
            CLIENT_LIMIT,
            id="projects-longest-titles",
        ),
        pytest.param(
            "get_work_hierarchy",
            {"limit": 100, "include_tasks": True},
            _check_hierarchy,
            MAX_TITLE,
            0,
            CLIENT_LIMIT,
            id="hierarchy-longest-titles",
        ),
        # Free text at its longest length: list rows carry only a description excerpt.
        pytest.param(
            "list_tasks",
            {"limit": 100},
            _check_tasks,
            MAX_TITLE,
            MAX_TEXT,
            CLIENT_LIMIT,
            id="tasks-longest-text",
        ),
        pytest.param(
            "list_projects",
            {"limit": 100},
            _check_projects,
            MAX_TITLE,
            MAX_TEXT,
            CLIENT_LIMIT,
            id="projects-longest-text",
        ),
    ],
)
async def test_list_and_board_results_stay_within_the_size_budget(
    tool: str,
    arguments: dict[str, Any],
    check: Callable[[Any], None],
    title_length: int,
    text_length: int,
    limit: int,
    capsys: pytest.CaptureFixture[str],
) -> None:
    container = create_container(make_settings(), database_factory())
    owner = container.auth.provision_user("owner", "Owner")
    _seed(container, owner, title_length, text_length)

    async with Client(_server_for(container, Actor(owner, READ_SCOPES))) as client:
        result = await client.call_tool(tool, arguments)

    check(result)
    size = _measured_size(result)
    with capsys.disabled():
        print(f"\n{tool} (titles {title_length}, text {text_length}) = {size} (limit {limit})")
    assert size <= limit, f"{tool} is over the {limit} character limit: {size}"
