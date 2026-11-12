"""Project dates and the pantry's "today" are the owner's calendar days, not UTC days.

The clock is frozen at 23:30 UTC on 28 October 2026, which is already 00:30 on 29 October in
Stockholm (CET, UTC+1).
"""

from datetime import UTC, date, datetime
from uuid import UUID
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy.orm import Session, sessionmaker

from sidekick.projects.application.service import ProjectService
from sidekick.shared.auth import AuthService
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.shared.types import Actor
from sidekick.shopping.application.schemas import BatchItem
from sidekick.shopping.application.service import ShoppingService
from sidekick.shopping.persistence.store import ShoppingStore
from sidekick.store import SqlAlchemyStore
from sidekick.work.application.models import WorkQuery
from sidekick.work.application.service import ContextService
from sidekick.work.application.work_lists import WorkListService
from tests.db import database_factory
from tests.support.fakes import make_cursor_codec

STOCKHOLM = ZoneInfo("Europe/Stockholm")
LATE_UTC = datetime(2026, 10, 28, 23, 30, tzinfo=UTC)
SCOPES = frozenset(
    {"projects:read", "projects:write", "tasks:read", "shopping:read", "shopping:write"}
)


class _Clock:
    def now(self) -> datetime:
        return LATE_UTC


def _owner() -> tuple[
    Actor, sessionmaker[Session], ContextService, WorkListService, ProjectService
]:
    factory = database_factory()
    owner_id = AuthService(factory, "pepper" * 8).provision_user("owner", "Owner")
    store = SqlAlchemyStore(factory)
    contexts = ContextService(store, _Clock(), make_cursor_codec(), owner_timezone=STOCKHOLM)
    work_lists = WorkListService(store, _Clock(), make_cursor_codec(), owner_timezone=STOCKHOLM)
    projects = ProjectService(store, _Clock(), make_cursor_codec())
    return Actor(owner_id, SCOPES), factory, contexts, work_lists, projects


@pytest.mark.integration
def test_project_target_date_groups_as_overdue_or_today_in_the_owner_zone() -> None:
    actor, _factory, contexts, work_lists, projects = _owner()
    domain = contexts.create_domain(
        actor, name="Hem", description=None, idempotency_key="zone-domain"
    )
    dated = {
        "Yesterday": date(2026, 10, 28),
        "Today": date(2026, 10, 29),
        "Tomorrow": date(2026, 10, 30),
    }
    for title, target in dated.items():
        projects.create(
            actor,
            title=title,
            domain_id=domain.id,
            target_date=target,
            idempotency_key=f"zone-project-{title}",
        )

    page = work_lists.work_agenda_page(actor, WorkQuery(kind="project"))
    groups = {item.title: item.agenda_group for item in page.items}

    # The target day itself is "today" until its end (23:59 Stockholm), whatever the UTC date.
    assert groups == {"Yesterday": "overdue", "Today": "today", "Tomorrow": "upcoming"}
    due = {item.title: item.due_at for item in page.items}
    assert due["Today"] == datetime(2026, 10, 29, 22, 59, tzinfo=UTC)


@pytest.mark.integration
def test_project_start_date_begins_at_local_midnight() -> None:
    actor, _factory, contexts, work_lists, projects = _owner()
    domain = contexts.create_domain(
        actor, name="Hem", description=None, idempotency_key="zone-domain-2"
    )
    projects.create(
        actor,
        title="Starts today",
        domain_id=domain.id,
        start_date=date(2026, 10, 29),
        target_date=date(2026, 10, 29),
        idempotency_key="zone-project-start",
    )

    page = work_lists.work_agenda_page(actor, WorkQuery(kind="project"))

    # 00:30 on 29 October in Stockholm is after that day's local midnight (23:00 UTC), so the
    # Project is already actionable; read as UTC midnight it would still be "scheduled later".
    assert [item.agenda_group for item in page.items] == ["today"]
    assert page.items[0].earliest_start == datetime(2026, 10, 28, 23, 0, tzinfo=UTC)
    assert page.items[0].actionable_now is True


@pytest.mark.integration
def test_pantry_today_is_the_owner_day() -> None:
    actor, factory, _contexts, _work_lists, _projects = _owner()
    telemetry = NoopTelemetryAdapter()
    service = ShoppingService(
        ShoppingStore(factory, telemetry),
        _Clock(),
        telemetry,
        owner_timezone=STOCKHOLM,
    )
    created = service.create_list(actor, "Fredag", idempotency_key="zone-list")
    list_id = UUID(created["shopping_list"]["id"])
    added = service.add_items(
        actor, list_id, [BatchItem(client_ref="a", name="Citron")], idempotency_key="zone-items"
    )
    item = added["items"][0]["item"]

    bought = service.set_purchased(
        actor, UUID(item["id"]), purchased=True, version=item["version"], idempotency_key="zone-buy"
    )
    read = service.get_list(actor, list_id)

    assert bought["evaluated_on"] == "2026-10-29"
    assert read["evaluated_on"] == "2026-10-29"
