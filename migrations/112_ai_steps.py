"""Let the owner hand steps of a Task to AI: a mark, a plan approval, a performer and runs.

`tasks.ai_possible_since` marks a Task as possible with AI, like `ambition_since`. When the owner
approves the plan, `tasks.ai_plan_digest` holds a digest of the plan's content and
`ai_plan_approved_at` the instant; both are NULL when no plan is approved (a Task whose plan
changed since no longer matches the digest and is not run). `ai_task_cap_microusd` is the
spending cap the owner set at approval; NULL means the instance default.

`steps.performer` says who does a Step: the owner (every existing Step) or AI. An AI Step carries
`ai_spec`, the validated instruction (`AiStepSpecV1`), and only an AI Step does.

`ai_step_runs` holds one row per attempt at an AI Step: its state, the result the owner reviews,
a question the AI asked and the owner's answer or comment, token counts and cost. Text of a result
is the owner's data; nothing here is logged.

Expand only: new nullable columns, one column with a default (existing Steps read as the owner's)
and one new table. The runtime role may read, insert and update the table; it can delete nothing
(the schema's default privileges would also grant DELETE, so the migration takes it away). A row
leaves with its Step or Task when that is erased permanently, through the foreign keys. The
rollback drops the columns and the table, which loses only the AI data.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"111_webhook_tokens"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.tasks
            ADD COLUMN ai_possible_since timestamp with time zone,
            ADD COLUMN ai_plan_digest character(64),
            ADD COLUMN ai_plan_approved_at timestamp with time zone,
            ADD COLUMN ai_task_cap_microusd bigint,
            ADD CONSTRAINT ck_tasks_ai_plan_approval
                CHECK ((ai_plan_digest IS NULL) = (ai_plan_approved_at IS NULL)),
            ADD CONSTRAINT ck_tasks_ai_task_cap
                CHECK (ai_task_cap_microusd IS NULL OR ai_task_cap_microusd > 0);
        ALTER TABLE sidekick.steps
            ADD COLUMN performer character varying(8) DEFAULT 'owner' NOT NULL,
            ADD COLUMN ai_spec jsonb,
            ADD CONSTRAINT ck_steps_performer CHECK (performer IN ('owner', 'ai')),
            ADD CONSTRAINT ck_steps_ai_spec
                CHECK ((performer = 'ai') = (ai_spec IS NOT NULL)),
            ADD CONSTRAINT ck_steps_ai_spec_size
                CHECK (ai_spec IS NULL OR octet_length(ai_spec::text) <= 12000);
        CREATE TABLE sidekick.ai_step_runs (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            task_id uuid NOT NULL,
            step_id uuid NOT NULL,
            attempt integer NOT NULL,
            runner character varying(12) NOT NULL,
            state character varying(16) NOT NULL,
            plan_digest character(64) NOT NULL,
            provider character varying(40),
            model character varying(120),
            worker_id character varying(80),
            lease_until timestamp with time zone,
            queued_at timestamp with time zone,
            started_at timestamp with time zone,
            finished_at timestamp with time zone,
            reviewed_at timestamp with time zone,
            result_format character varying(16),
            result_text text,
            result_summary character varying(500),
            checklist jsonb,
            question character varying(1000),
            answer character varying(1000),
            feedback character varying(1000),
            input_tokens bigint DEFAULT 0 NOT NULL,
            output_tokens bigint DEFAULT 0 NOT NULL,
            cache_read_tokens bigint DEFAULT 0 NOT NULL,
            cache_write_tokens bigint DEFAULT 0 NOT NULL,
            reserved_microusd bigint DEFAULT 0 NOT NULL,
            cost_microusd bigint DEFAULT 0 NOT NULL,
            cost_source character varying(16) DEFAULT 'none' NOT NULL,
            error_category character varying(24),
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT ai_step_runs_pkey PRIMARY KEY (id),
            CONSTRAINT uq_ai_step_runs_step_attempt UNIQUE (step_id, attempt),
            CONSTRAINT ck_ai_step_runs_attempt CHECK (attempt >= 1),
            CONSTRAINT ck_ai_step_runs_version CHECK (version >= 1),
            CONSTRAINT ck_ai_step_runs_runner CHECK (runner IN ('claude_code', 'server')),
            CONSTRAINT ck_ai_step_runs_state CHECK (
                state IN (
                    'queued', 'running', 'to_review', 'needs_input', 'failed', 'cancelled',
                    'accepted', 'rejected', 'redo', 'answered'
                )
            ),
            CONSTRAINT ck_ai_step_runs_cost_source
                CHECK (cost_source IN ('provider', 'price_table', 'client_estimate', 'none')),
            CONSTRAINT ck_ai_step_runs_result_text
                CHECK (result_text IS NULL OR char_length(result_text) <= 32000),
            CONSTRAINT ck_ai_step_runs_counts CHECK (
                input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0
                AND cache_write_tokens >= 0 AND reserved_microusd >= 0 AND cost_microusd >= 0
            ),
            CONSTRAINT ai_step_runs_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_step_runs_step_owner FOREIGN KEY (step_id, owner_id)
                REFERENCES sidekick.steps(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_ai_step_runs_task_owner FOREIGN KEY (task_id, owner_id)
                REFERENCES sidekick.tasks(id, owner_id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX uq_ai_step_runs_one_active
            ON sidekick.ai_step_runs USING btree (step_id)
            WHERE state IN ('queued', 'running');
        CREATE INDEX ix_ai_step_runs_owner_state
            ON sidekick.ai_step_runs USING btree (owner_id, state);
        CREATE INDEX ix_ai_step_runs_owner_created
            ON sidekick.ai_step_runs USING btree (owner_id, created_at);
        CREATE INDEX ix_ai_step_runs_task ON sidekick.ai_step_runs USING btree (task_id);
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.ai_step_runs TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.ai_step_runs FROM sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.ai_step_runs;
        ALTER TABLE sidekick.steps
            DROP CONSTRAINT IF EXISTS ck_steps_ai_spec_size,
            DROP CONSTRAINT IF EXISTS ck_steps_ai_spec,
            DROP CONSTRAINT IF EXISTS ck_steps_performer,
            DROP COLUMN IF EXISTS ai_spec,
            DROP COLUMN IF EXISTS performer;
        ALTER TABLE sidekick.tasks
            DROP CONSTRAINT IF EXISTS ck_tasks_ai_task_cap,
            DROP CONSTRAINT IF EXISTS ck_tasks_ai_plan_approval,
            DROP COLUMN IF EXISTS ai_task_cap_microusd,
            DROP COLUMN IF EXISTS ai_plan_approved_at,
            DROP COLUMN IF EXISTS ai_plan_digest,
            DROP COLUMN IF EXISTS ai_possible_since;
        """,
    )
]
