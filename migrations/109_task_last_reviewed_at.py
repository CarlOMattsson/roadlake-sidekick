"""Remember when the owner last went through a Task in a review of many Tasks.

`tasks.last_reviewed_at` is the instant a review decision (keep, done, move, waiting, flag) last
touched the Task. The review queue is derived from it: an open Task that was never reviewed, or not
in the last seven days, is due for review again. Ordinary edits leave it alone.

Expand only: one nullable column, no default and no index; existing rows read as never reviewed.
The rollback drops the column, which forgets when each Task was last reviewed and nothing else.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"108_memory_forgotten_facts"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.tasks ADD COLUMN last_reviewed_at timestamp with time zone;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.tasks DROP COLUMN IF EXISTS last_reviewed_at;
        """,
    )
]
