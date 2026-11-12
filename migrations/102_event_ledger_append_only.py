"""Make the domain event ledger and the activity projection append-only for the app role.

The 0.1.0 baseline granted `sidekick_app` SELECT, INSERT, UPDATE and DELETE on
`sidekick.domain_events` and `sidekick.activity_entries`, although the runtime only ever inserts and
reads them (`AutomationService` appends a ledger row and its projection row; nothing updates or
deletes either). `sidekick.audit_events` was already granted SELECT and INSERT only. This revokes
UPDATE and DELETE so a runtime bug or a compromised app credential cannot rewrite or erase the
history. The owner role keeps full access for retention and tests. Deleting a user still removes
their rows: a foreign-key `ON DELETE CASCADE` runs with the table owner's rights, not the caller's.
Downgrade restores the baseline grants.
"""

# migration-class: contract
# A REVOKE narrows what the app role may do, which the migration policy treats as a contract step.

from yoyo import step

__depends__ = {"101_tasks_project_and_due_indexes"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        REVOKE UPDATE, DELETE ON sidekick.domain_events FROM sidekick_app;
        REVOKE UPDATE, DELETE ON sidekick.activity_entries FROM sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        GRANT UPDATE, DELETE ON sidekick.activity_entries TO sidekick_app;
        GRANT UPDATE, DELETE ON sidekick.domain_events TO sidekick_app;
        """,
    )
]
