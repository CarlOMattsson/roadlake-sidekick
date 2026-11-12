"""Concrete transaction adapter, assembled in the composition layer.

`SqlAlchemyStore` is a thin composition: each context's owner-filtered operations live in a
mixin in that context's `persistence` module (for example `sidekick.contacts.persistence`), and
`StoreBase` in `sidekick.shared.persistence.stores` holds the session factory, the transaction
boundary, idempotency and audit. It sits beside `sidekick.composition` because it imports every
context, which the shared kernel must not.
"""

from sidekick.automation.persistence import AutomationStoreMixin
from sidekick.contacts.persistence import ContactStore
from sidekick.journal.persistence.drafts import JournalDraftStore
from sidekick.journal.persistence.entries import JournalEntryStore
from sidekick.journal.persistence.summaries import JournalSummaryStore
from sidekick.lifecycle.persistence import LifecycleStore
from sidekick.shared.persistence.stores.base import StoreBase
from sidekick.tasks.persistence import ProjectTaskStore
from sidekick.work.persistence.listing import WorkListStore
from sidekick.work.persistence.steps_actions import StepActionStore
from sidekick.work.persistence.structure import WorkStructureStore
from sidekick.work.persistence.tags import WorkTagStore

__all__ = ["SqlAlchemyStore"]


class SqlAlchemyStore(
    AutomationStoreMixin,
    LifecycleStore,
    WorkStructureStore,
    ProjectTaskStore,
    StepActionStore,
    WorkTagStore,
    WorkListStore,
    ContactStore,
    JournalEntryStore,
    JournalSummaryStore,
    JournalDraftStore,
    StoreBase,
):
    """Short-lived transaction boundary with owner-filtered feature operations."""
