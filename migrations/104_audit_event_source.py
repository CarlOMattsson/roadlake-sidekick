"""Record who made a change: the owner in the app, or the model through a tool.

`sidekick.audit_events` gets a nullable `source` column, `'you'` or `'claude'`. The recent-changes
list reads it to say whether a change was made by the owner or by Claude. Rows written before this
migration, and rows written by a background job, keep NULL, which the list reports as unknown.

The column holds one of two fixed words, never text from a record. The migration is additive
(migration class `expand`): no rows change, and `sidekick_app` already holds SELECT and INSERT on
the whole table, so the grants stay as they were. Downgrade drops the constraint and the column.
"""

from yoyo import step

__depends__ = {"103_trash_sweep_delete_grants"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.audit_events ADD COLUMN source character varying(16);
        ALTER TABLE sidekick.audit_events
          ADD CONSTRAINT audit_events_source_check CHECK ((source IN ('you', 'claude')));
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.audit_events DROP CONSTRAINT audit_events_source_check;
        ALTER TABLE sidekick.audit_events DROP COLUMN source;
        """,
    )
]
