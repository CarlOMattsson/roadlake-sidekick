"""The store of the Journal use cases."""

from uuid import UUID

from sqlalchemy.orm import Session, sessionmaker

from sidekick.contacts.domain.contact import Contact
from sidekick.contacts.domain.ports import ContactReader
from sidekick.journal.persistence.drafts import JournalDraftStore
from sidekick.journal.persistence.entries import JournalEntryStore
from sidekick.journal.persistence.summaries import JournalSummaryStore
from sidekick.projects.domain import Project
from sidekick.projects.domain.ports import ProjectReader
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.shared.types import TxSession
from sidekick.tasks.domain import Task
from sidekick.tasks.domain.ports import TaskReader
from sidekick.work.domain.tag_assignment import RecordTagReader
from sidekick.work.persistence.tags import RecordTagRelay


class SqlJournalStore(
    JournalEntryStore, JournalSummaryStore, JournalDraftStore, RecordTagRelay, StoreBase
):
    """The Journal operations plus what they borrow from other contexts.

    An entry relates to Projects, Tasks and Contacts and carries tags, so the reads of those and
    the tag operations are delegated to the ports the store was built with.
    """

    def __init__(
        self,
        session_factory: sessionmaker[Session],
        telemetry: TelemetryPort | None = None,
        *,
        projects: ProjectReader,
        tasks: TaskReader,
        contacts: ContactReader,
        tags: RecordTagReader,
    ) -> None:
        super().__init__(session_factory, telemetry)
        self._projects = projects
        self._tasks = tasks
        self._contacts = contacts
        self._tags = tags

    def get_project(self, session: TxSession, owner_id: UUID, project_id: UUID) -> Project:
        return self._projects.get_project(session, owner_id, project_id)

    def get_task(self, session: TxSession, owner_id: UUID, task_id: UUID) -> Task:
        return self._tasks.get_task(session, owner_id, task_id)

    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact:
        return self._contacts.get_contact(session, owner_id, contact_id, include_archived)
