"""Index the AI Step runs the server queues and runs.

The AI worker looks for queued server runs and for server runs whose lease ran out. A partial
index keeps those two lookups small however many finished runs the table holds.

Expand only: one new index and nothing else, so no data moves and the rollback just drops it. The
table's grants are unchanged.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"112_ai_steps"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE INDEX ix_ai_step_runs_server_queue
            ON sidekick.ai_step_runs USING btree (lease_until)
            WHERE runner = 'server'
                AND (state IN ('queued', 'running') OR reserved_microusd > 0);
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP INDEX IF EXISTS sidekick.ix_ai_step_runs_server_queue;
        """,
    )
]
