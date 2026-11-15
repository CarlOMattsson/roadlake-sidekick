"""Let the owner keep a Task as an ambition: something to have in view, never to be reminded of.

`tasks.ambition_since` is the instant the Task became an ambition; NULL is an ordinary Task. An
ambition has no due date, start date, waiting, flag or reminders, so it is never late, never in
the review queue and never in the day's agenda. Making it a task again clears the column.

Expand only: one nullable column, no default and no index; existing rows read as ordinary Tasks.
The rollback drops the column, which turns every ambition back into an ordinary undated Task and
loses nothing else.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"109_task_last_reviewed_at"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.tasks ADD COLUMN ambition_since timestamp with time zone;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.tasks DROP COLUMN IF EXISTS ambition_since;
        """,
    )
]
