"""Let the app role permanently remove trashed Domains and Processes.

Permanent removal (`RecordLifecycleService.permanently_remove`, and the operator sweep
`sidekick-admin empty-trash` on top of it) issues `DELETE` through the ordinary application
connection. The 0.1.0 baseline granted `sidekick_app` only SELECT, INSERT and UPDATE on
`sidekick.domains` and `sidekick.processes`, so a standard installation refused the sweep with a
permission error for those two kinds, while the other kinds (Tasks,
Steps, Actions, Projects, Contacts) already held DELETE.

This adds DELETE on exactly those two tables. A narrower route would need a second login role for
the CLI that the runtime never uses; the same use case also runs inside the API, so the application
role is the one that needs the right. Nothing else changes:

* `sidekick.journal_entries` stays SELECT, INSERT and UPDATE only. Since the Journal feature
  (D-031 added trash later) the runtime never erases a Journal entry, and a test pins the refusal.
  Permanent removal therefore refuses a Journal entry with a safe error and the sweep counts it as
  kept (`NOT_REMOVABLE`); erasing trashed entries is not supported.
* `sidekick.journal_sources` stays SELECT and INSERT only. A Journal source is immutable and cannot
  be trashed (the `FOR UPDATE` lock the trash step takes needs UPDATE).
* `sidekick.shopping_items` keeps no DELETE; shopping items are not removable.
* `sidekick.domain_events`, `sidekick.activity_entries` and `sidekick.audit_events` stay
  append-only (migration 102). The history keeps the titles and descriptions it recorded.

The grant is additive, so the migration class is `expand`. Downgrade restores the baseline grants.
"""

from yoyo import step

__depends__ = {"102_event_ledger_append_only"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        GRANT DELETE ON sidekick.domains TO sidekick_app;
        GRANT DELETE ON sidekick.processes TO sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        REVOKE DELETE ON sidekick.processes FROM sidekick_app;
        REVOKE DELETE ON sidekick.domains FROM sidekick_app;
        """,
    )
]
