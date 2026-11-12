"""Index the Task lookups by Project and by due time.

Both are additive: two partial indexes on `tasks`, nothing is dropped or changed (migration class
`expand`).

* `ix_tasks_owner_project (owner_id, project_id)` serves the Project views (list, done/total counts,
  estimate totals) and the `ON DELETE RESTRICT` check of `fk_tasks_project_owner`, which looks for
  Tasks by exactly these two columns whenever a Project is deleted. Before it, each of those reads
  scanned every Task of the owner through `ix_tasks_owner_updated`.
* `ix_tasks_owner_due (owner_id, due_at)` serves the agenda/Today windows and the periodic reminder
  scan, which read only dated Tasks.

Measured with EXPLAIN on 5 000 Tasks for one owner (100 000 in the table): a Project read went from
about 2 200 buffer hits to about 250, a due-window read from about 2 200 to about 45.

The indexes are built in the migration's transaction, which holds a write lock on `tasks` while they
build. That is short for the Task volume of one owner (a fraction of a second at 100 000 rows).
"""

from yoyo import step

__depends__ = {"100_baseline_0_1_0"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE INDEX ix_tasks_owner_project ON sidekick.tasks (owner_id, project_id)
          WHERE project_id IS NOT NULL;
        CREATE INDEX ix_tasks_owner_due ON sidekick.tasks (owner_id, due_at)
          WHERE due_at IS NOT NULL;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP INDEX sidekick.ix_tasks_owner_due;
        DROP INDEX sidekick.ix_tasks_owner_project;
        """,
    )
]
