"""Links from Journal entries to Projects and Contacts: checks, changes and reads."""

from uuid import UUID

from sidekick.journal.application.models import MAX_RELATIONS_PER_KIND, RelationChange
from sidekick.journal.application.store import JournalStore
from sidekick.journal.domain.records import EntryRelations, RelationLabels
from sidekick.projects.domain import ProjectStatus
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.types import Actor, TxSession
from sidekick.tasks.domain import TaskStatus


def bounded_unique_ids(values: tuple[UUID, ...], field_name: str) -> tuple[UUID, ...]:
    values = tuple(values)
    if len(values) > MAX_RELATIONS_PER_KIND:
        raise ValidationError(f"{field_name} must contain at most 25 identifiers")
    if len(values) != len(set(values)):
        raise ValidationError(f"{field_name} must contain unique identifiers")
    return values


def checked_relation_change(actor: Actor, change: RelationChange) -> RelationChange:
    """Bounds the id lists and requires the read scope of every kind the change names."""

    change = RelationChange(
        add_project_ids=bounded_unique_ids(change.add_project_ids, "add_project_ids"),
        remove_project_ids=bounded_unique_ids(change.remove_project_ids, "remove_project_ids"),
        add_contact_ids=bounded_unique_ids(change.add_contact_ids, "add_contact_ids"),
        remove_contact_ids=bounded_unique_ids(change.remove_contact_ids, "remove_contact_ids"),
    )
    if change.add_project_ids or change.remove_project_ids:
        actor.require("projects:read")
    if change.add_contact_ids or change.remove_contact_ids:
        actor.require("contacts:read")
    if set(change.add_project_ids) & set(change.remove_project_ids) or set(
        change.add_contact_ids
    ) & set(change.remove_contact_ids):
        raise ValidationError("a link cannot be both added and removed")
    return change


def require_active_links(
    store: JournalStore,
    session: TxSession,
    actor: Actor,
    project_ids: tuple[UUID, ...],
    task_ids: tuple[UUID, ...],
    contact_ids: tuple[UUID, ...],
) -> None:
    for project_id in sorted(project_ids, key=lambda value: value.int):
        project = store.get_project(session, actor.user_id, project_id)
        if project.status is ProjectStatus.COMPLETED:
            raise NotFoundError("project not found")
    for task_id in sorted(task_ids, key=lambda value: value.int):
        task = store.get_task(session, actor.user_id, task_id)
        if task.status is TaskStatus.COMPLETED:
            raise NotFoundError("task not found")
    for contact_id in sorted(contact_ids, key=lambda value: value.int):
        contact = store.get_contact(session, actor.user_id, contact_id)
        if contact.archived:
            raise NotFoundError("contact not found")


def changes_links(
    store: JournalStore, session: TxSession, actor: Actor, entry_id: UUID, change: RelationChange
) -> bool:
    """Whether the change adds a missing link or removes a present one."""

    current = store.get_journal_entry_relations(session, actor.user_id, entry_id)
    return (
        any(i not in current.project_ids for i in change.add_project_ids)
        or any(i in current.project_ids for i in change.remove_project_ids)
        or any(i not in current.contact_ids for i in change.add_contact_ids)
        or any(i in current.contact_ids for i in change.remove_contact_ids)
    )


def apply_relation_change(
    store: JournalStore, session: TxSession, actor: Actor, entry_id: UUID, change: RelationChange
) -> None:
    """Add and remove links inside the entry's transaction, with the creation checks.

    Added Projects and Contacts must be the owner's and active, as when the entry is created.
    A link that is already there is not added again and a link that is not there is not
    removed, so the call can be repeated and an undo is simply the opposite change.
    """

    current = store.get_journal_entry_relations(session, actor.user_id, entry_id)
    add_projects = tuple(i for i in change.add_project_ids if i not in current.project_ids)
    add_contacts = tuple(i for i in change.add_contact_ids if i not in current.contact_ids)
    drop_projects = tuple(i for i in change.remove_project_ids if i in current.project_ids)
    drop_contacts = tuple(i for i in change.remove_contact_ids if i in current.contact_ids)
    require_active_links(store, session, actor, add_projects, (), add_contacts)
    kept_projects = len(current.project_ids) - len(drop_projects) + len(add_projects)
    kept_contacts = len(current.contact_ids) - len(drop_contacts) + len(add_contacts)
    if max(kept_projects, kept_contacts) > MAX_RELATIONS_PER_KIND:
        raise ValidationError("an entry can hold at most 25 Projects and 25 Contacts")
    if drop_projects or drop_contacts:
        store.remove_journal_entry_relations(
            session,
            owner_id=actor.user_id,
            entry_id=entry_id,
            project_ids=drop_projects,
            contact_ids=drop_contacts,
        )
    if add_projects or add_contacts:
        store.add_journal_entry_relations(
            session,
            owner_id=actor.user_id,
            entry_id=entry_id,
            project_ids=add_projects,
            task_ids=(),
            contact_ids=add_contacts,
        )


class JournalRelationService:
    """Reads of the Projects and Contacts an entry is linked to."""

    def __init__(self, store: JournalStore) -> None:
        self.store = store

    def get_entry_relations(self, actor: Actor, entry_id: UUID) -> EntryRelations:
        actor.require("journal:read")
        relation_reader = getattr(self.store, "get_journal_entry_relations", None)
        if relation_reader is None:
            return EntryRelations()
        return self.store.transaction(
            lambda session: relation_reader(session, actor.user_id, entry_id)
        )

    def get_entries_relations(
        self, actor: Actor, entry_ids: tuple[UUID, ...], *, with_labels: bool
    ) -> dict[UUID, tuple[EntryRelations, RelationLabels | None]]:
        """Links, and with `with_labels` their names, of several entries in one transaction.

        The same links and names `get_entry_relations` and `get_relation_labels` give per entry:
        a kind's names need its read scope.
        """

        actor.require("journal:read")
        relation_reader = getattr(self.store, "get_journal_entries_relations", None)
        if relation_reader is None or not entry_ids:
            return {entry_id: (EntryRelations(), None) for entry_id in entry_ids}
        label_reader = getattr(self.store, "get_journal_relation_labels", None)
        can_name_projects = with_labels and "projects:read" in actor.scopes
        can_name_contacts = with_labels and "contacts:read" in actor.scopes

        def read(session: TxSession) -> dict[UUID, tuple[EntryRelations, RelationLabels | None]]:
            relations = relation_reader(session, actor.user_id, entry_ids)
            project_ids = tuple(
                {i for r in relations.values() for i in r.project_ids} if can_name_projects else ()
            )
            contact_ids = tuple(
                {i for r in relations.values() for i in r.contact_ids} if can_name_contacts else ()
            )
            names = (
                label_reader(session, actor.user_id, project_ids, contact_ids)
                if label_reader is not None and (project_ids or contact_ids)
                else RelationLabels(projects={}, contacts={})
            )
            return {
                entry_id: (
                    relations[entry_id],
                    RelationLabels(
                        projects={
                            i: names.projects[i]
                            for i in relations[entry_id].project_ids
                            if i in names.projects
                        },
                        contacts={
                            i: names.contacts[i]
                            for i in relations[entry_id].contact_ids
                            if i in names.contacts
                        },
                    )
                    if with_labels
                    else None,
                )
                for entry_id in entry_ids
            }

        return self.store.transaction(read)

    def get_relation_labels(self, actor: Actor, relations: EntryRelations) -> RelationLabels:
        """Names of the linked Projects and Contacts; none for a kind the actor may not read."""

        reader = getattr(self.store, "get_journal_relation_labels", None)
        project_ids = relations.project_ids if "projects:read" in actor.scopes else ()
        contact_ids = relations.contact_ids if "contacts:read" in actor.scopes else ()
        if reader is None or not (project_ids or contact_ids):
            return RelationLabels(projects={}, contacts={})
        return self.store.transaction(
            lambda session: reader(session, actor.user_id, project_ids, contact_ids)
        )
