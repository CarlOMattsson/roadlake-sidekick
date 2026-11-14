"""The read other contexts' stores borrow from Contacts."""

from datetime import datetime
from typing import Protocol
from uuid import UUID

from sidekick.contacts.domain.contact import Contact
from sidekick.shared.types import TxSession


class ContactReader(Protocol):
    def get_contact(
        self,
        session: TxSession,
        owner_id: UUID,
        contact_id: UUID,
        include_archived: bool = False,
    ) -> Contact: ...


class TaskContactLinker(ContactReader, Protocol):
    """The Contact read and the Contact link a Task's use cases write."""

    def link_task_contact(
        self, session: TxSession, owner_id: UUID, task_id: UUID, contact_id: UUID
    ) -> datetime | None: ...
