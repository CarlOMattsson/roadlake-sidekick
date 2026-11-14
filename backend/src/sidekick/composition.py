"""Composition root: the `Container` of services and the function that builds it.

FastAPI (`sidekick.api.app`), the MCP entrances and the worker all compose the same container.
This module imports neither interface layer, so each of them can depend on it without a cycle.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import TYPE_CHECKING
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.activity.application.service import ActivityLedger, ActivityService
from sidekick.activity.persistence import ActivityStore
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.push import PushSubscriptionService
from sidekick.companion.push_outbox_store import install_wake_hook
from sidekick.companion.push_reminder_store import SqlReminderStore
from sidekick.companion.push_reminders import ReminderService
from sidekick.companion.push_subscription_store import SqlPushSubscriptionStore
from sidekick.companion.service import CompanionDeviceService
from sidekick.contacts.application.relations import ContactRelationService
from sidekick.contacts.application.service import ContactService
from sidekick.contacts.persistence import ContactStore, SqlContactStore
from sidekick.journal.application.analysis import JournalAnalysisService
from sidekick.journal.application.capture import JournalCaptureService
from sidekick.journal.application.day import JournalDayService
from sidekick.journal.application.finalize import JournalFinalizeService
from sidekick.journal.application.relations import JournalRelationService
from sidekick.journal.application.service import JournalService
from sidekick.journal.persistence.store import SqlJournalStore
from sidekick.license.persistence import LicenseStore
from sidekick.license.service import LicenseService
from sidekick.lifecycle.application import RecordLifecycleService
from sidekick.lifecycle.application.empty_trash import EmptyTrashResult, empty_trash
from sidekick.lifecycle.persistence import LifecycleStore
from sidekick.memory.application.settings import provision_owner_settings
from sidekick.memory.application.store import MemoryStore
from sidekick.memory.factory import build_provider as build_memory_provider
from sidekick.memory.infrastructure.store import SqlAlchemyMemoryStore
from sidekick.memory.ports import MemoryProvider
from sidekick.projects.application import ProjectService
from sidekick.references.persistence import ExternalReferenceStore
from sidekick.references.service import ExternalReferenceService
from sidekick.search.persistence import SearchStore
from sidekick.search.service import SearchService
from sidekick.shared.auth import AuthService
from sidekick.shared.config import Settings
from sidekick.shared.observability import TelemetryPort, configure_observability
from sidekick.shared.persistence import create_session_factory
from sidekick.shared.types import CursorCodec, SystemClock
from sidekick.shopping.application.service import ShoppingService
from sidekick.shopping.persistence.store import ShoppingStore
from sidekick.tasks.application import TaskBoardService, TaskBulkService, TaskService
from sidekick.tasks.persistence import ProjectTaskStore, SqlTaskStore
from sidekick.work.application.process_runs import ProcessRunService
from sidekick.work.application.saved_views import SavedViewService
from sidekick.work.application.service import ContextService
from sidekick.work.application.steps_service import StepsService
from sidekick.work.application.tags_service import WorkTagService
from sidekick.work.application.work_lists import WorkListService
from sidekick.work.persistence.steps_actions import StepActionStore
from sidekick.work.persistence.store import SqlWorkStore
from sidekick.work.persistence.structure import WorkStructureStore
from sidekick.work.persistence.tags import WorkTagStore

if TYPE_CHECKING:
    from starlette.requests import Request

# The session factory type, named here so the transport layers (`api`, `mcp`) can type the test
# seam of `create_app` without importing SQLAlchemy themselves.
SessionFactory = sessionmaker[Session]


@dataclass(slots=True)
class Container:
    settings: Settings
    session_factory: SessionFactory
    auth: AuthService
    projects: ProjectService
    contexts: ContextService
    work_lists: WorkListService
    steps: StepsService
    saved_views: SavedViewService
    work_tags: WorkTagService
    tasks: TaskService
    task_board: TaskBoardService
    task_bulk: TaskBulkService
    contacts: ContactService
    contact_relations: ContactRelationService
    journal: JournalService
    journal_capture: JournalCaptureService
    journal_day: JournalDayService
    journal_relations: JournalRelationService
    shopping: ShoppingService
    references: ExternalReferenceService
    search: SearchService
    journal_analysis: JournalAnalysisService
    journal_finalize: JournalFinalizeService
    activity: ActivityService
    lifecycle: RecordLifecycleService
    process_runs: ProcessRunService
    # The Android companion's services (ADR-005): pairing and device tokens, push endpoints, and
    # the reminders the phone fetches. The companion routes reach them only through here.
    companion_devices: CompanionDeviceService
    push_subscriptions: PushSubscriptionService
    reminders: ReminderService
    # The instance's license key and its display state (D-081: offline signed license keys);
    # checked offline.
    license: LicenseService
    # Derived-memory provider, built once from settings; None when memory is off.
    memory: MemoryProvider | None
    memory_store: MemoryStore
    telemetry: TelemetryPort


def container_of(request: "Request") -> Container:
    """The `Container` the application was created with; typed access for route handlers."""

    container: Container = request.app.state.container
    return container


def _memory_provider(settings: Settings) -> MemoryProvider | None:
    """The derived-memory provider the settings select, or None while memory is off."""

    if not settings.memory_enabled:
        return None
    return build_memory_provider(settings)


def create_auth_service(
    factory: SessionFactory, settings: Settings, memory_store: MemoryStore | None = None
) -> AuthService:
    """The `AuthService` wired with what a new owner needs from the other contexts.

    A new owner gets the default memory settings row in the transaction that creates the user.
    Every entrance that provisions users builds its `AuthService` here, not directly.
    """

    store = memory_store or SqlAlchemyMemoryStore(factory)

    def provision_memory(session: Session, owner_id: UUID, now: datetime) -> None:
        provision_owner_settings(store, session, owner_id, now)

    return AuthService(factory, settings.token_pepper, on_user_provisioned=(provision_memory,))


def create_lifecycle_service(
    factory: SessionFactory, telemetry: TelemetryPort, settings: Settings
) -> RecordLifecycleService:
    """The one wiring of the lifecycle use case: the API, MCP tools and the admin sweep share it."""

    return RecordLifecycleService(
        LifecycleStore(factory, telemetry),
        SystemClock(),
        CursorCodec(settings.cursor_signing_key),
        contact_removal_guard=ShoppingStore.ensure_contact_unlinked,
        task_removal_hook=ExternalReferenceStore.release_task_references,
        locale=settings.mcp_app_locale,
    )


def create_admin_lifecycle_service(
    factory: SessionFactory, settings: Settings
) -> RecordLifecycleService:
    """The lifecycle use case for `sidekick-admin`, which has no container and serves nothing."""

    return create_lifecycle_service(
        factory, configure_observability(settings.environment), settings
    )


def sweep_trash_for_admin(
    lifecycle: RecordLifecycleService,
    *,
    remove: bool,
    older_than: timedelta | None,
    correlation_id: str,
) -> EmptyTrashResult:
    """Run the operator's trash sweep; `sidekick.admin.cli` reaches it only through here."""

    return empty_trash(
        lifecycle, remove=remove, older_than=older_than, correlation_id=correlation_id
    )


@dataclass(frozen=True, slots=True)
class ContextStores:
    """One store per context over the same session factory.

    A context's store holds only that context's operations plus the few reads it borrows from
    another context, which are handed in here as ports. The operations are static, so the owning
    store class is the port; nothing here is shared state.
    """

    tasks: SqlTaskStore
    contacts: SqlContactStore
    journal: SqlJournalStore
    work: SqlWorkStore
    tags: WorkTagStore


def create_stores(factory: SessionFactory, telemetry: TelemetryPort | None = None) -> ContextStores:
    """Build the context stores and wire the reads they borrow from each other."""

    return ContextStores(
        tasks=SqlTaskStore(
            factory,
            telemetry,
            contacts=ContactStore,
            structure=WorkStructureStore,
            steps=StepActionStore,
            tags=WorkTagStore,
        ),
        contacts=SqlContactStore(
            factory,
            telemetry,
            projects=ProjectTaskStore,
            tasks=ProjectTaskStore,
            tags=WorkTagStore,
        ),
        journal=SqlJournalStore(
            factory,
            telemetry,
            projects=ProjectTaskStore,
            tasks=ProjectTaskStore,
            contacts=ContactStore,
            tags=WorkTagStore,
        ),
        work=SqlWorkStore(factory, telemetry),
        tags=WorkTagStore(factory, telemetry),
    )


def create_container(
    settings: Settings,
    session_factory: SessionFactory | None = None,
    telemetry: TelemetryPort | None = None,
) -> Container:
    factory = session_factory or create_session_factory(
        settings.database_url,
        require_unprivileged_role=settings.environment == "production",
        timeouts=settings.database_timeouts,
    )
    if settings.push_enabled:
        # Task and Step changes queue a wake push in the writing transaction (ADR-005, D-078: push
        # through UnifiedPush).
        install_wake_hook(
            factory, min_interval=timedelta(seconds=settings.push_wake_min_interval_seconds)
        )
    resolved_telemetry = telemetry or configure_observability(settings.environment)
    stores = create_stores(factory, resolved_telemetry)
    cursor_codec = CursorCodec(settings.cursor_signing_key)
    activity_store = ActivityStore(factory, resolved_telemetry)
    activity_ledger = ActivityLedger(activity_store)
    activity_service = ActivityService(activity_store, cursor_codec)
    tasks = TaskService(
        stores.tasks,
        SystemClock(),
        cursor_codec,
        activity_ledger,
        owner_timezone=settings.owner_zone,
    )
    projects = ProjectService(stores.tasks, SystemClock(), cursor_codec)
    contexts = ContextService(
        stores.work, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
    )
    work_lists = WorkListService(
        stores.work, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
    )
    steps = StepsService(stores.work, SystemClock(), cursor_codec)
    contacts = ContactService(stores.contacts, SystemClock(), cursor_codec)
    memory_store = SqlAlchemyMemoryStore(factory)
    auth_service = create_auth_service(factory, settings, memory_store)
    container = Container(
        settings=settings,
        session_factory=factory,
        auth=auth_service,
        projects=projects,
        contexts=contexts,
        work_lists=work_lists,
        steps=steps,
        saved_views=SavedViewService(stores.work, SystemClock()),
        work_tags=WorkTagService(stores.tags, SystemClock(), cursor_codec),
        tasks=tasks,
        task_board=TaskBoardService(stores.tasks, SystemClock()),
        task_bulk=TaskBulkService(tasks),
        contacts=contacts,
        contact_relations=ContactRelationService(stores.contacts, SystemClock(), cursor_codec),
        journal=JournalService(stores.journal, SystemClock(), cursor_codec),
        journal_capture=JournalCaptureService(stores.journal, SystemClock()),
        journal_day=JournalDayService(
            stores.journal, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
        ),
        journal_relations=JournalRelationService(stores.journal),
        shopping=ShoppingService(
            ShoppingStore(factory, resolved_telemetry),
            SystemClock(),
            resolved_telemetry,
            owner_timezone=settings.owner_zone,
        ),
        references=ExternalReferenceService(
            ExternalReferenceStore(factory, resolved_telemetry),
            SystemClock(),
            resolved_telemetry,
            cursor_codec,
        ),
        search=SearchService(
            SearchStore(factory, resolved_telemetry), cursor_codec, resolved_telemetry
        ),
        journal_analysis=JournalAnalysisService(stores.journal, SystemClock()),
        journal_finalize=JournalFinalizeService(stores.journal, SystemClock()),
        activity=activity_service,
        lifecycle=create_lifecycle_service(factory, resolved_telemetry, settings),
        process_runs=ProcessRunService(stores.work, tasks, SystemClock(), activity_ledger),
        companion_devices=CompanionDeviceService(CompanionDeviceStore(factory), auth_service),
        push_subscriptions=PushSubscriptionService.from_settings(
            SqlPushSubscriptionStore(factory), settings
        ),
        reminders=ReminderService(SqlReminderStore(factory), locale=settings.mcp_app_locale),
        license=LicenseService(LicenseStore(factory), settings.license_public_key),
        memory=_memory_provider(settings),
        memory_store=memory_store,
        telemetry=resolved_telemetry,
    )

    return container
