"""Applying an approved suggestion's effect through the Task and Contact use cases.

The catalogue is closed (`create_task`, `create_contact`), so this is the one place that turns a
validated payload into the command of the use case that owns the record. Both use cases run in the
caller's open transaction: the record, its audit row and the suggestion's own decision commit or
roll back together. The scope check is the caller's (`SuggestionService`), which holds the actor.
"""

from sidekick.automations.domain.effects import CreateTaskV1, ParsedPayload
from sidekick.automations.domain.suggestion import AppliedRecord
from sidekick.contacts.application.models import CreateContactCommand
from sidekick.contacts.application.service import ContactService
from sidekick.shared.types import Actor, TxSession
from sidekick.tasks.application.service import TaskService
from sidekick.tasks.domain import NewTaskPayload
from sidekick.tasks.domain.planning import due_on_day


class ServiceEffectApplier:
    def __init__(self, tasks: TaskService, contacts: ContactService) -> None:
        self.tasks = tasks
        self.contacts = contacts

    def create(
        self, session: TxSession, actor: Actor, parsed: ParsedPayload, correlation_id: str | None
    ) -> AppliedRecord:
        """Create the record the payload describes and return it with its version."""

        value = parsed.value
        if isinstance(value, CreateTaskV1):
            task = self.tasks.create_in_session(
                session, actor, self._task_payload(value), correlation_id
            )
            return AppliedRecord("task", task.id, task.version)
        contact = self.contacts.create_in_session(
            session,
            actor,
            CreateContactCommand(
                display_name=value.display_name,
                email=value.email,
                phone=value.phone,
                organization=value.organization,
                role=value.role,
                context_note=value.context_note,
            ),
            correlation_id,
        )
        return AppliedRecord("contact", contact.id, contact.version)

    def _task_payload(self, value: CreateTaskV1) -> NewTaskPayload:
        due_at = (
            due_on_day(None, value.due_on, self.tasks.owner_timezone)
            if value.due_on is not None
            else None
        )
        return {
            "title": value.title,
            "project_id": str(value.project_id) if value.project_id else None,
            "domain_id": None,
            "process_id": None,
            "description": value.description,
            "priority": value.priority,
            "due_at": due_at,
            "not_before": None,
            "estimated_minutes": None,
            "blocked_reminder_cadence": None,
            "blocked_reminder_snoozed_until": None,
            "recurrence": None,
            "tags": [],
        }
