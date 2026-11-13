"""Composition root: the `Container` of services and the function that builds it.

FastAPI (`sidekick.api.app`), the MCP entrances and the worker all compose the same container.
This module imports neither interface layer, so each of them can depend on it without a cycle.
"""

from dataclasses import dataclass
from datetime import datetime, timedelta
from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.automation.application.service import ActivityLedger, AutomationPolicyService
from sidekick.companion.persistence import CompanionDeviceStore
from sidekick.companion.push import PushSubscriptionService
from sidekick.companion.push_outbox_store import install_wake_hook
from sidekick.companion.push_reminder_store import SqlReminderStore
from sidekick.companion.push_reminders import ReminderService
from sidekick.companion.push_subscription_store import SqlPushSubscriptionStore
from sidekick.companion.service import CompanionDeviceService
from sidekick.contacts.application.relations import ContactRelationService
from sidekick.contacts.application.service import ContactService
from sidekick.journal.application.analysis import JournalAnalysisService
from sidekick.journal.application.capture import JournalCaptureService
from sidekick.journal.application.day import JournalDayService
from sidekick.journal.application.finalize import JournalFinalizeService
from sidekick.journal.application.relations import JournalRelationService
from sidekick.journal.application.service import JournalService
from sidekick.license.persistence import LicenseStore
from sidekick.license.service import LicenseService
from sidekick.lifecycle.application import RecordLifecycleService
from sidekick.lifecycle.application.empty_trash import EmptyTrashResult, empty_trash
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
from sidekick.store import SqlAlchemyStore
from sidekick.tasks.application import TaskBoardService, TaskBulkService, TaskService
from sidekick.work.application.process_runs import ProcessRunService
from sidekick.work.application.saved_views import SavedViewService
from sidekick.work.application.service import ContextService
from sidekick.work.application.steps_service import StepsService
from sidekick.work.application.tags_service import WorkTagService
from sidekick.work.application.work_lists import WorkListService

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
    automation: AutomationPolicyService
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


def create_lifecycle_service(store: SqlAlchemyStore, settings: Settings) -> RecordLifecycleService:
    """The one wiring of the lifecycle use case: the API, MCP tools and the admin sweep share it."""

    return RecordLifecycleService(
        store,
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

    store = SqlAlchemyStore(factory, configure_observability(settings.environment))
    return create_lifecycle_service(store, settings)


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
    store = SqlAlchemyStore(factory, resolved_telemetry)
    cursor_codec = CursorCodec(settings.cursor_signing_key)
    activity_ledger = ActivityLedger(store)
    automation_service = AutomationPolicyService(store, SystemClock(), cursor_codec)
    tasks = TaskService(
        store, SystemClock(), cursor_codec, activity_ledger, owner_timezone=settings.owner_zone
    )
    projects = ProjectService(store, SystemClock(), cursor_codec)
    contexts = ContextService(
        store, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
    )
    work_lists = WorkListService(
        store, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
    )
    steps = StepsService(store, SystemClock(), cursor_codec)
    contacts = ContactService(store, SystemClock(), cursor_codec)
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
        saved_views=SavedViewService(store, SystemClock()),
        work_tags=WorkTagService(store, SystemClock(), cursor_codec),
        tasks=tasks,
        task_board=TaskBoardService(store, SystemClock()),
        task_bulk=TaskBulkService(tasks),
        contacts=contacts,
        contact_relations=ContactRelationService(store, SystemClock(), cursor_codec),
        journal=JournalService(store, SystemClock(), cursor_codec),
        journal_capture=JournalCaptureService(store, SystemClock()),
        journal_day=JournalDayService(
            store, SystemClock(), cursor_codec, owner_timezone=settings.owner_zone
        ),
        journal_relations=JournalRelationService(store),
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
        journal_analysis=JournalAnalysisService(store, SystemClock()),
        journal_finalize=JournalFinalizeService(store, SystemClock()),
        automation=automation_service,
        lifecycle=create_lifecycle_service(store, settings),
        process_runs=ProcessRunService(store, tasks, SystemClock(), activity_ledger),
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
