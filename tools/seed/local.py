"""Seeding stages for a local Sidekick database.

Every write goes through the same application use cases that FastAPI routes and
FastMCP tools call, so seeded rows respect domain invariants, ownership, and audit
behavior. Content lives in `dataset.py`; identity lives in `config.py`.

This is not perfectly idempotent. Each stage has one cheap guard instead:

* user       - created only when the login is missing (existing credentials kept)
* structure  - domains, processes, and projects are reused when the name exists
* tasks      - skipped entirely when more than 5 tasks already exist
* contacts   - skipped entirely when 5 or more contacts already exist
* journal    - skipped entirely when 2 or more entries already exist
"""

import argparse
import os
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from uuid import UUID, uuid4

from sidekick.composition import create_auth_service
from sidekick.contacts.application.service import ContactService, CreateContactCommand
from sidekick.journal.application.capture import JournalCaptureService
from sidekick.journal.application.service import JournalService
from sidekick.journal.domain.entry import KeyPoint
from sidekick.projects.application import ProjectService
from sidekick.shared.auth import ALL_SCOPES, AuthService
from sidekick.shared.config import Settings, get_settings
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.types import Actor, CursorCodec, SystemClock
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import TaskService
from sidekick.tasks.domain import Task, TaskStatus
from sidekick.work.application.service import ContextService
from sidekick.work.application.steps_service import StepsService
from sqlalchemy.engine import make_url

from tools.seed.config import SeedSettings, get_seed_settings
from tools.seed.dataset import (
    CONTACTS,
    DOMAINS,
    JOURNAL_ENTRIES,
    PROCESSES,
    PROJECTS,
    TASKS,
)

TASK_SKIP_ABOVE = 5
CONTACT_SKIP_AT = 5
JOURNAL_SKIP_AT = 2

LOCAL_DB_HOSTS = frozenset({"localhost", "127.0.0.1", "::1", ""})
AUTOMATION_MARKERS = ("CI", "GITHUB_ACTIONS", "BUILD_NUMBER")
MAX_JOURNAL_LOOKBACK_DAYS = 364


@dataclass(slots=True)
class Counters:
    created: dict[str, int] = field(default_factory=dict)
    skipped: list[str] = field(default_factory=list)

    def add(self, label: str, amount: int = 1) -> None:
        self.created[label] = self.created.get(label, 0) + amount

    def skip(self, message: str) -> None:
        self.skipped.append(message)


@dataclass(slots=True)
class Services:
    """The application use cases the seeder drives, wired like the API container."""

    auth: AuthService
    contexts: ContextService
    projects: ProjectService
    tasks: TaskService
    steps: StepsService
    contacts: ContactService
    journal: JournalService
    journal_capture: JournalCaptureService


def log(message: str) -> None:
    print(f"[seed] {message}", flush=True)


def guard_manual_only(confirmed: bool, settings: Settings) -> None:
    """Fail closed unless this is an explicit, local, manual invocation."""

    if not confirmed:
        raise SystemExit(
            "refusing to seed without --confirm; this writes fake data and is intended "
            "for manual one-off local use only"
        )
    automation = [name for name in AUTOMATION_MARKERS if os.environ.get(name)]
    if automation:
        raise SystemExit(
            f"refusing to seed inside automation (set: {', '.join(automation)})"
        )
    if settings.environment == "production":
        raise SystemExit("refusing to seed a production environment")
    host = (make_url(settings.database_url).host or "").lower()
    if host not in LOCAL_DB_HOSTS:
        raise SystemExit(
            f"refusing to seed non-local database host {host!r}; "
            "point SIDEKICK_DATABASE_URL at a local database first"
        )


def build_services(settings: Settings) -> Services:
    session_factory = create_session_factory(settings.database_url)
    store = SqlAlchemyStore(session_factory)
    clock = SystemClock()
    cursor_codec = CursorCodec(settings.cursor_signing_key)
    return Services(
        auth=create_auth_service(session_factory, settings),
        contexts=ContextService(
            store, clock, cursor_codec, owner_timezone=settings.owner_zone
        ),
        projects=ProjectService(store, clock, cursor_codec),
        tasks=TaskService(store, clock, cursor_codec),
        steps=StepsService(store, clock, cursor_codec),
        contacts=ContactService(store, clock, cursor_codec),
        journal=JournalService(store, clock, cursor_codec),
        journal_capture=JournalCaptureService(store, clock),
    )


def ensure_user(auth: AuthService, seed: SeedSettings, counters: Counters) -> UUID:
    user_id, created = auth.ensure_user(seed.login, seed.display_name)
    if created:
        counters.add("users")
        log(f"created user {seed.login!r} ({user_id})")
    else:
        counters.skip(f"user {seed.login!r} already exists; left untouched")
        log(f"user {seed.login!r} already exists ({user_id}); skipping creation")
    return user_id


def key(prefix: str) -> str:
    """Fresh idempotency key per call; duplicate protection comes from the stage guards."""

    return f"seed-local:{prefix}:{uuid4()}"


def seed_structure(
    actor: Actor,
    contexts: ContextService,
    projects: ProjectService,
    counters: Counters,
) -> tuple[dict[str, UUID], dict[str, UUID], dict[str, UUID]]:
    domain_ids = {
        item.name: item.id for item in contexts.list_domains(actor, limit=100).items
    }
    for domain_spec in DOMAINS:
        if domain_spec.name in domain_ids:
            log(f"domain {domain_spec.name!r} already exists; reusing")
            continue
        domain = contexts.create_domain(
            actor,
            name=domain_spec.name,
            description=domain_spec.description,
            idempotency_key=key("domain"),
        )
        domain_ids[domain.name] = domain.id
        counters.add("domains")
        log(f"created domain {domain.name!r}")

    process_ids = {
        item.name: item.id for item in contexts.list_processes(actor, limit=100).items
    }
    for process_spec in PROCESSES:
        if process_spec.name in process_ids:
            log(f"process {process_spec.name!r} already exists; reusing")
            continue
        process = contexts.create_process(
            actor,
            domain_id=domain_ids[process_spec.domain],
            name=process_spec.name,
            description=process_spec.description,
            idempotency_key=key("process"),
        )
        process_ids[process.name] = process.id
        counters.add("processes")
        log(f"created process {process.name!r} under {process_spec.domain!r}")

    project_ids = {
        item.title: item.id
        for item in projects.list(actor, limit=100, include_archived=True).items
    }
    today = date.today()
    for project_spec in PROJECTS:
        if project_spec.title in project_ids:
            log(f"project {project_spec.title!r} already exists; reusing")
            continue
        project = projects.create(
            actor,
            title=project_spec.title,
            description=project_spec.description,
            start_date=today + timedelta(days=project_spec.start_offset_days),
            target_date=today + timedelta(days=project_spec.target_offset_days),
            domain_id=domain_ids[project_spec.domain],
            idempotency_key=key("project"),
        )
        project_ids[project.title] = project.id
        counters.add("projects")
        log(f"created project {project.title!r} under {project_spec.domain!r}")

    return domain_ids, process_ids, project_ids


def seed_tasks(
    actor: Actor,
    tasks: TaskService,
    steps: StepsService,
    domain_ids: dict[str, UUID],
    process_ids: dict[str, UUID],
    project_ids: dict[str, UUID],
    counters: Counters,
) -> None:
    existing = tasks.list(actor, limit=TASK_SKIP_ABOVE + 1).items
    if len(existing) > TASK_SKIP_ABOVE:
        counters.skip(
            f"tasks, steps, and actions: more than {TASK_SKIP_ABOVE} tasks already exist"
        )
        log(f"more than {TASK_SKIP_ABOVE} tasks already exist; skipping task seeding")
        return

    parents = {"domain": domain_ids, "process": process_ids, "project": project_ids}
    now = datetime.now(UTC)
    for task_spec in TASKS:
        parent_id = parents[task_spec.parent_kind][task_spec.parent_name]
        task = tasks.create(
            actor,
            title=task_spec.title,
            description=task_spec.description,
            priority=task_spec.priority,
            due_at=_offset(now, task_spec.due_offset_days),
            idempotency_key=key("task"),
            domain_id=parent_id if task_spec.parent_kind == "domain" else None,
            process_id=parent_id if task_spec.parent_kind == "process" else None,
            project_id=parent_id if task_spec.parent_kind == "project" else None,
        )
        counters.add("tasks")
        for step_spec in task_spec.steps:
            step = steps.create_step(
                actor,
                task.id,
                title=step_spec.title,
                due_at=_offset(now, step_spec.due_offset_days),
                idempotency_key=key("step"),
            )
            counters.add("steps")
            for action_spec in step_spec.actions:
                steps.create_action(
                    actor,
                    step.id,
                    title=action_spec.title,
                    due_at=_offset(now, action_spec.due_offset_days),
                    idempotency_key=key("action"),
                )
                counters.add("actions")
        log(
            f"created task {task_spec.title!r} ({task_spec.parent_kind} {task_spec.parent_name!r})"
        )


def seed_contacts(
    actor: Actor,
    contacts: ContactService,
    open_tasks: dict[str, UUID],
    counters: Counters,
) -> None:
    existing = contacts.list(actor, limit=CONTACT_SKIP_AT, include_archived=True).items
    if len(existing) >= CONTACT_SKIP_AT:
        counters.skip(
            f"contacts and task links: {CONTACT_SKIP_AT} or more contacts already exist"
        )
        log(
            f"{CONTACT_SKIP_AT} or more contacts already exist; skipping contact seeding"
        )
        return

    for contact_spec in CONTACTS:
        contact = contacts.create(
            actor,
            CreateContactCommand(
                display_name=contact_spec.display_name,
                context_note=contact_spec.context_note,
                email=contact_spec.email,
                phone=contact_spec.phone,
                aliases=list(contact_spec.aliases) or None,
            ),
            idempotency_key=key("contact"),
        )
        counters.add("contacts")
        links = 0
        for title in contact_spec.task_titles:
            task_id = open_tasks.get(title)
            if task_id is None:
                continue
            contacts.link_task(
                actor, contact.id, task_id, idempotency_key=key("contact-link")
            )
            counters.add("contact_task_links")
            links += 1
        log(f"created contact {contact.display_name!r} with {links} task link(s)")


def seed_journal(
    actor: Actor,
    journal: JournalService,
    journal_capture: JournalCaptureService,
    project_ids: dict[str, UUID],
    open_tasks: dict[str, UUID],
    contact_ids: dict[str, UUID],
    counters: Counters,
) -> None:
    today = date.today()
    existing = journal.list_entries(
        actor,
        start_date=today - timedelta(days=MAX_JOURNAL_LOOKBACK_DAYS),
        end_date=today + timedelta(days=1),
        include_archived=True,
        limit=JOURNAL_SKIP_AT,
    ).items
    if len(existing) >= JOURNAL_SKIP_AT:
        counters.skip(f"journal: {JOURNAL_SKIP_AT} or more entries already exist")
        log(
            f"{JOURNAL_SKIP_AT} or more journal entries already exist; skipping journal seeding"
        )
        return

    for journal_spec in JOURNAL_ENTRIES:
        journal_date = today + timedelta(days=journal_spec.day_offset)
        occurred_at = datetime(
            journal_date.year,
            journal_date.month,
            journal_date.day,
            journal_spec.hour,
            tzinfo=UTC,
        )
        source = journal_capture.create_source(
            actor,
            source_type=journal_spec.source_type,
            journal_date=journal_date,
            occurred_at=occurred_at,
            source_recorded_at=occurred_at,
            raw_text=journal_spec.raw_text,
            language="sv",
            replaces_source_id=None,
            idempotency_key=key("journal-source"),
        )
        counters.add("journal_sources")
        entry = journal_capture.create_manual_entry(
            actor,
            source_id=source.id,
            title=journal_spec.title,
            summary=journal_spec.summary,
            key_points=tuple(
                KeyPoint(kind=kind, text=text) for kind, text in journal_spec.key_points
            ),
            project_ids=_lookup(project_ids, journal_spec.project_titles),
            task_ids=_lookup(open_tasks, journal_spec.task_titles),
            contact_ids=_lookup(contact_ids, journal_spec.contact_names),
            idempotency_key=key("journal-entry"),
        )
        counters.add("journal_entries")
        log(f"created journal entry {entry.title!r} for {journal_date.isoformat()}")


def _offset(now: datetime, days: int | None) -> datetime | None:
    return None if days is None else now + timedelta(days=days)


def _lookup(source: dict[str, UUID], names: tuple[str, ...]) -> tuple[UUID, ...]:
    """Relate only to entities that actually exist, so partial databases still seed."""

    return tuple(source[name] for name in names if name in source)


def _open_tasks(tasks: TaskService, actor: Actor) -> dict[str, UUID]:
    items: list[Task] = tasks.list(actor, limit=100).items
    return {
        item.title: item.id
        for item in items
        if item.status is not TaskStatus.COMPLETED and item.archived_at is None
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="python -m tools.seed",
        description="Manually seed a local Sidekick database with fake test data.",
    )
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="required acknowledgement that fake data will be written to the local database",
    )
    args = parser.parse_args(argv)

    settings = get_settings()
    guard_manual_only(args.confirm, settings)
    seed = get_seed_settings()

    url = make_url(settings.database_url)
    log(
        f"environment={settings.environment} database={url.render_as_string(hide_password=True)}"
    )

    services = build_services(settings)
    counters = Counters()
    actor = Actor(ensure_user(services.auth, seed, counters), ALL_SCOPES)

    domain_ids, process_ids, project_ids = seed_structure(
        actor, services.contexts, services.projects, counters
    )
    seed_tasks(
        actor,
        services.tasks,
        services.steps,
        domain_ids,
        process_ids,
        project_ids,
        counters,
    )
    open_tasks = _open_tasks(services.tasks, actor)
    seed_contacts(actor, services.contacts, open_tasks, counters)
    contact_ids = {
        item.display_name: item.id
        for item in services.contacts.list(actor, limit=100).items
    }
    seed_journal(
        actor,
        services.journal,
        services.journal_capture,
        project_ids,
        open_tasks,
        contact_ids,
        counters,
    )

    log("--- summary ---")
    if counters.created:
        for label in sorted(counters.created):
            log(f"created {label}: {counters.created[label]}")
    else:
        log("created nothing; every stage was already populated")
    for message in counters.skipped:
        log(f"skipped {message}")
    log(
        f"seeded data belongs to user {seed.login!r}; there is no web shell. "
        "Open it from Claude through the Sidekick MCP connector as this user "
        "(create a token with `sidekick-admin create-token`, see QUICKSTART.md)"
    )
    return 0
