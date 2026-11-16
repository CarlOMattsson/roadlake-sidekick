"""Keep what an AI Step run cost after its Step or Task is erased permanently.

The monthly spending cap and the daily limit of starts add up the runs in `ai_step_runs`. A run
leaves that table with its Step or Task through the foreign keys, so erasing a Task would also
erase what it had cost and let the owner spend the same money again. `ai_erased_run_costs` keeps
one row per erased run: only numbers and identifiers (the run, its owner and Task, the runner, the
cost source, what the run cost or had reserved, and when it was created), never any text. A
trigger on `ai_step_runs` writes the row just before the run is deleted. It writes nothing when
the owner's account itself is being erased, so no cost outlives the account (the foreign key then
removes the rows).

The trigger function runs with the schema owner's rights, so the runtime role needs no write
privilege on the new table: it may only read it. The schema's default privileges would also grant
it INSERT, UPDATE and DELETE, so the migration takes them away.

Expand only: one new table, one function and one trigger; no existing data is touched. The
rollback drops all three, which only loses the costs of runs erased since.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"113_ai_server_queue"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE TABLE sidekick.ai_erased_run_costs (
            run_id uuid NOT NULL,
            owner_id uuid NOT NULL,
            task_id uuid NOT NULL,
            runner character varying(12) NOT NULL,
            cost_source character varying(16) NOT NULL,
            cost_microusd bigint NOT NULL,
            created_at timestamp with time zone NOT NULL,
            CONSTRAINT ai_erased_run_costs_pkey PRIMARY KEY (run_id),
            CONSTRAINT ck_ai_erased_run_costs_runner
                CHECK (runner IN ('claude_code', 'server')),
            CONSTRAINT ck_ai_erased_run_costs_cost_source
                CHECK (cost_source IN ('provider', 'price_table', 'client_estimate', 'none')),
            CONSTRAINT ck_ai_erased_run_costs_cost CHECK (cost_microusd >= 0),
            CONSTRAINT ai_erased_run_costs_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE
        );
        CREATE INDEX ix_ai_erased_run_costs_owner_created
            ON sidekick.ai_erased_run_costs USING btree (owner_id, created_at);
        GRANT SELECT ON TABLE sidekick.ai_erased_run_costs TO sidekick_app;
        REVOKE INSERT, UPDATE, DELETE ON TABLE sidekick.ai_erased_run_costs FROM sidekick_app;
        CREATE FUNCTION sidekick.keep_erased_ai_run_cost() RETURNS trigger
            LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, pg_temp
            AS $$
        BEGIN
            INSERT INTO sidekick.ai_erased_run_costs
                (run_id, owner_id, task_id, runner, cost_source, cost_microusd, created_at)
            SELECT OLD.id, u.id, OLD.task_id, OLD.runner, OLD.cost_source,
                   OLD.cost_microusd + OLD.reserved_microusd, OLD.created_at
            FROM sidekick.users u
            WHERE u.id = OLD.owner_id;
            RETURN OLD;
        END
        $$;
        CREATE TRIGGER trg_ai_step_runs_keep_cost
            BEFORE DELETE ON sidekick.ai_step_runs
            FOR EACH ROW EXECUTE FUNCTION sidekick.keep_erased_ai_run_cost();
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TRIGGER IF EXISTS trg_ai_step_runs_keep_cost ON sidekick.ai_step_runs;
        DROP FUNCTION IF EXISTS sidekick.keep_erased_ai_run_cost();
        DROP TABLE IF EXISTS sidekick.ai_erased_run_costs;
        """,
    )
]
