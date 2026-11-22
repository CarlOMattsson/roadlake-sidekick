"""Add the tables for automations: the registry, its runs, the facts and suggestions they produce.

An automation is its own aggregate and never a Task, so no everyday view, search or memory path can
show it. `automations` is the owner's registry: a trusted instruction, the effects it may propose,
the cadence, the approval (`approved_digest` equals `spec_digest` when the owner approved exactly
this definition) and the spending limit of one run (`run_budget_microusd`, one US dollar by
default). `model_tier` says which model class runs it: `standard` (a very cheap model) or `strong`
(the configured Anthropic model). The tier is one of the fields `spec_digest` is computed over, so
changing it takes the approval away like any other change of the definition; the digest itself is
computed by the application, not here.

`automation_runs` holds one row per attempt at one occurrence and is also the queue of the server
runner; at most one attempt per occurrence is active (`queued`, `running` or `checking`) at a time.
`automation_datapoints` holds the facts a run read (never actions), `automation_suggestions` the
decision cards drafted from them, `automation_checks` one row per independent check of a
suggestion, and `automation_report_cursors` the point up to which the owner has seen the report.
Text written by the AI (`summary`, `rationale`, `source_label`) is untrusted and is shown escaped.
Text the owner or a source supplied is the owner's data; nothing here is logged.

Expand only: six new tables and nothing else; no existing data is touched. The runtime role may
read, insert and update the tables, but it can delete nothing and cannot change the schema (the
schema's default privileges would also grant DELETE, so the migration takes it away). A table with
no UPDATE for it (`automation_checks`) is append-only. A row leaves only with its owner's account,
through the foreign keys, which the database applies on its own. A datapoint or a suggestion points
at its run through `(run_id, automation_id, owner_id)`, so it belongs to the automation and the
owner of that run and to no other. An automation is archived, never
erased, so the cost of its runs stays counted. The rollback drops the six tables, which loses only
the automation data.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"115_contact_slack_profile"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;

        CREATE TABLE sidekick.automations (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            title character varying(120) NOT NULL,
            purpose character varying(300) NOT NULL,
            instruction text NOT NULL,
            sources character varying(16)[] DEFAULT '{}' NOT NULL,
            runner character varying(12) NOT NULL,
            cadence jsonb NOT NULL,
            allowed_effects character varying(32)[] DEFAULT '{}' NOT NULL,
            apply_mode character varying(16) DEFAULT 'suggest' NOT NULL,
            auto_effects character varying(32)[] DEFAULT '{}' NOT NULL,
            bulk_threshold smallint DEFAULT 90 NOT NULL,
            auto_threshold smallint DEFAULT 95 NOT NULL,
            max_suggestions_per_run smallint DEFAULT 15 NOT NULL,
            run_budget_microusd bigint DEFAULT 1000000 NOT NULL,
            model_tier character varying(12) DEFAULT 'standard' NOT NULL,
            state character varying(12) DEFAULT 'draft' NOT NULL,
            spec_digest character(64) NOT NULL,
            approved_digest character(64),
            approved_at timestamp with time zone,
            last_run_at timestamp with time zone,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT automations_pkey PRIMARY KEY (id),
            CONSTRAINT uq_automations_id_owner UNIQUE (id, owner_id),
            CONSTRAINT ck_automations_instruction
                CHECK (char_length(instruction) BETWEEN 1 AND 4000),
            CONSTRAINT ck_automations_sources CHECK (
                sources <@ ARRAY['mail', 'calendar', 'chat', 'web', 'sidekick', 'manual']
                    ::character varying[]
            ),
            CONSTRAINT ck_automations_runner
                CHECK (runner IN ('claude', 'claude_code', 'server', 'any')),
            CONSTRAINT ck_automations_cadence CHECK (
                jsonb_typeof(cadence) = 'object' AND octet_length(cadence::text) <= 2048
            ),
            CONSTRAINT ck_automations_allowed_effects CHECK (
                allowed_effects <@ ARRAY[
                    'create_task', 'create_contact', 'add_shopping_items',
                    'link_contact_to_task', 'add_contact_detail'
                ]::character varying[]
            ),
            CONSTRAINT ck_automations_apply_mode
                CHECK (apply_mode IN ('suggest', 'auto_low_risk')),
            CONSTRAINT ck_automations_auto_effects CHECK (
                auto_effects <@ allowed_effects
                AND auto_effects <@ ARRAY['create_task', 'create_contact']::character varying[]
                AND (apply_mode = 'auto_low_risk' OR cardinality(auto_effects) = 0)
            ),
            CONSTRAINT ck_automations_bulk_threshold CHECK (bulk_threshold BETWEEN 80 AND 99),
            CONSTRAINT ck_automations_auto_threshold
                CHECK (auto_threshold BETWEEN 90 AND 99 AND auto_threshold >= bulk_threshold),
            CONSTRAINT ck_automations_max_suggestions
                CHECK (max_suggestions_per_run BETWEEN 1 AND 25),
            CONSTRAINT ck_automations_run_budget CHECK (run_budget_microusd > 0),
            CONSTRAINT ck_automations_model_tier CHECK (model_tier IN ('standard', 'strong')),
            CONSTRAINT ck_automations_state
                CHECK (state IN ('draft', 'active', 'paused', 'archived')),
            CONSTRAINT ck_automations_approval
                CHECK ((approved_digest IS NULL) = (approved_at IS NULL)),
            CONSTRAINT ck_automations_version CHECK (version >= 1),
            CONSTRAINT automations_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE
        );
        COMMENT ON COLUMN sidekick.automations.model_tier IS
            'Model class that runs the automation; one of the fields spec_digest covers.';
        CREATE INDEX ix_automations_owner_state
            ON sidekick.automations USING btree (owner_id, state);

        CREATE TABLE sidekick.automation_runs (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            automation_id uuid NOT NULL,
            occurrence_key character varying(40) NOT NULL,
            attempt integer NOT NULL,
            runner character varying(12) NOT NULL,
            state character varying(12) NOT NULL,
            stage character varying(10),
            spec_digest character(64) NOT NULL,
            session_digest character(64),
            credential_kind character varying(12) NOT NULL,
            worker_id character varying(80),
            lease_until timestamp with time zone,
            queued_at timestamp with time zone,
            started_at timestamp with time zone,
            finished_at timestamp with time zone,
            datapoint_count integer DEFAULT 0 NOT NULL,
            suggestion_count integer DEFAULT 0 NOT NULL,
            rejected_count integer DEFAULT 0 NOT NULL,
            flagged_count integer DEFAULT 0 NOT NULL,
            auto_applied_count integer DEFAULT 0 NOT NULL,
            summary character varying(300),
            outcome character varying(16),
            model character varying(120),
            checker_model character varying(120),
            input_tokens bigint DEFAULT 0 NOT NULL,
            output_tokens bigint DEFAULT 0 NOT NULL,
            cache_read_tokens bigint DEFAULT 0 NOT NULL,
            cache_write_tokens bigint DEFAULT 0 NOT NULL,
            reserved_microusd bigint DEFAULT 0 NOT NULL,
            cost_microusd bigint DEFAULT 0 NOT NULL,
            cost_source character varying(16) DEFAULT 'none' NOT NULL,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT automation_runs_pkey PRIMARY KEY (id),
            CONSTRAINT uq_automation_runs_id_owner UNIQUE (id, owner_id),
            CONSTRAINT uq_automation_runs_id_automation_owner
                UNIQUE (id, automation_id, owner_id),
            CONSTRAINT uq_automation_runs_occurrence_attempt
                UNIQUE (automation_id, occurrence_key, attempt),
            CONSTRAINT ck_automation_runs_attempt CHECK (attempt >= 1),
            CONSTRAINT ck_automation_runs_version CHECK (version >= 1),
            CONSTRAINT ck_automation_runs_runner
                CHECK (runner IN ('claude', 'claude_code', 'server')),
            CONSTRAINT ck_automation_runs_state CHECK (
                state IN ('queued', 'running', 'checking', 'done', 'failed', 'cancelled', 'lapsed')
            ),
            CONSTRAINT ck_automation_runs_stage
                CHECK (stage IS NULL OR stage IN ('extract', 'propose', 'check')),
            CONSTRAINT ck_automation_runs_credential_kind
                CHECK (credential_kind IN ('token', 'oauth', 'worker')),
            CONSTRAINT ck_automation_runs_outcome CHECK (
                outcome IS NULL OR outcome IN (
                    'ok', 'nothing_found', 'failed', 'budget', 'invalid_output', 'provider',
                    'refused'
                )
            ),
            CONSTRAINT ck_automation_runs_cost_source
                CHECK (cost_source IN ('provider', 'price_table', 'client_estimate', 'none')),
            CONSTRAINT ck_automation_runs_counts CHECK (
                datapoint_count >= 0 AND suggestion_count >= 0 AND rejected_count >= 0
                AND flagged_count >= 0 AND auto_applied_count >= 0
            ),
            CONSTRAINT ck_automation_runs_amounts CHECK (
                input_tokens >= 0 AND output_tokens >= 0 AND cache_read_tokens >= 0
                AND cache_write_tokens >= 0 AND reserved_microusd >= 0 AND cost_microusd >= 0
            ),
            CONSTRAINT automation_runs_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_automation_runs_automation_owner FOREIGN KEY (automation_id, owner_id)
                REFERENCES sidekick.automations(id, owner_id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX uq_automation_runs_one_active
            ON sidekick.automation_runs USING btree (automation_id, occurrence_key)
            WHERE state IN ('queued', 'running', 'checking');
        CREATE INDEX ix_automation_runs_owner_state
            ON sidekick.automation_runs USING btree (owner_id, state);
        CREATE INDEX ix_automation_runs_owner_created
            ON sidekick.automation_runs USING btree (owner_id, created_at);
        CREATE INDEX ix_automation_runs_automation
            ON sidekick.automation_runs USING btree (automation_id, created_at);
        CREATE INDEX ix_automation_runs_server_queue
            ON sidekick.automation_runs USING btree (lease_until)
            WHERE runner = 'server'
                AND (state IN ('queued', 'running', 'checking') OR reserved_microusd > 0);

        CREATE TABLE sidekick.automation_datapoints (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            run_id uuid NOT NULL,
            automation_id uuid NOT NULL,
            kind character varying(16) NOT NULL,
            fields jsonb,
            source_kind character varying(12) NOT NULL,
            source_fingerprint character(64) NOT NULL,
            source_label character varying(160),
            source_received_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL,
            purge_after timestamp with time zone NOT NULL,
            purged_at timestamp with time zone,
            CONSTRAINT automation_datapoints_pkey PRIMARY KEY (id),
            CONSTRAINT uq_automation_datapoints_id_owner UNIQUE (id, owner_id),
            CONSTRAINT ck_automation_datapoints_kind CHECK (
                kind IN ('person', 'organisation', 'event', 'commitment', 'request', 'note')
            ),
            CONSTRAINT ck_automation_datapoints_fields CHECK (
                fields IS NULL
                OR (jsonb_typeof(fields) = 'object' AND octet_length(fields::text) <= 4096)
            ),
            CONSTRAINT ck_automation_datapoints_purged
                CHECK ((fields IS NULL) = (purged_at IS NOT NULL)),
            CONSTRAINT ck_automation_datapoints_source_kind CHECK (
                source_kind IN ('mail', 'calendar', 'chat', 'web', 'api', 'share', 'sidekick')
            ),
            CONSTRAINT automation_datapoints_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_automation_datapoints_run_automation_owner
                FOREIGN KEY (run_id, automation_id, owner_id)
                REFERENCES sidekick.automation_runs(id, automation_id, owner_id)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_automation_datapoints_run
            ON sidekick.automation_datapoints USING btree (run_id);
        CREATE INDEX ix_automation_datapoints_purge
            ON sidekick.automation_datapoints USING btree (purge_after)
            WHERE purged_at IS NULL;

        CREATE TABLE sidekick.automation_suggestions (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            automation_id uuid NOT NULL,
            run_id uuid NOT NULL,
            effect character varying(32) NOT NULL,
            effect_version smallint NOT NULL,
            payload jsonb,
            proposed_payload jsonb,
            rationale character varying(300),
            datapoint_ids uuid[] DEFAULT '{}' NOT NULL,
            dedupe_fingerprint character(64) NOT NULL,
            state character varying(12) NOT NULL,
            screening_flags character varying(32)[] DEFAULT '{}' NOT NULL,
            check_state character varying(12) DEFAULT 'off' NOT NULL,
            verdict character varying(12),
            confidence smallint,
            bulk_eligible boolean DEFAULT false NOT NULL,
            decided_at timestamp with time zone,
            decided_by character varying(8),
            decision_channel character varying(12),
            applied_kind character varying(24),
            applied_id uuid,
            applied_version integer,
            undone_at timestamp with time zone,
            apply_error character varying(24),
            expires_at timestamp with time zone NOT NULL,
            payload_purged_at timestamp with time zone,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT automation_suggestions_pkey PRIMARY KEY (id),
            CONSTRAINT uq_automation_suggestions_id_owner UNIQUE (id, owner_id),
            CONSTRAINT uq_automation_suggestions_dedupe
                UNIQUE (automation_id, dedupe_fingerprint),
            CONSTRAINT ck_automation_suggestions_effect CHECK (
                effect IN (
                    'create_task', 'create_contact', 'add_shopping_items',
                    'link_contact_to_task', 'add_contact_detail'
                )
            ),
            CONSTRAINT ck_automation_suggestions_effect_version CHECK (effect_version >= 1),
            CONSTRAINT ck_automation_suggestions_payload CHECK (
                payload IS NULL
                OR (jsonb_typeof(payload) = 'object' AND octet_length(payload::text) <= 8192)
            ),
            CONSTRAINT ck_automation_suggestions_proposed_payload CHECK (
                proposed_payload IS NULL
                OR (
                    jsonb_typeof(proposed_payload) = 'object'
                    AND octet_length(proposed_payload::text) <= 8192
                )
            ),
            CONSTRAINT ck_automation_suggestions_purged CHECK (
                (payload IS NULL) = (payload_purged_at IS NOT NULL)
                AND (proposed_payload IS NULL) = (payload_purged_at IS NOT NULL)
            ),
            CONSTRAINT ck_automation_suggestions_datapoints
                CHECK (cardinality(datapoint_ids) <= 10),
            CONSTRAINT ck_automation_suggestions_flags CHECK (cardinality(screening_flags) <= 16),
            CONSTRAINT ck_automation_suggestions_state CHECK (
                state IN (
                    'received', 'checking', 'pending', 'applied', 'undone', 'dismissed',
                    'expired'
                )
            ),
            CONSTRAINT ck_automation_suggestions_check_state
                CHECK (check_state IN ('off', 'queued', 'checked', 'failed')),
            CONSTRAINT ck_automation_suggestions_verdict
                CHECK (verdict IS NULL OR verdict IN ('ok', 'uncertain', 'suspicious')),
            CONSTRAINT ck_automation_suggestions_confidence
                CHECK (confidence IS NULL OR confidence BETWEEN 0 AND 100),
            CONSTRAINT ck_automation_suggestions_decision CHECK (
                (decided_at IS NULL) = (decided_by IS NULL)
                AND (decided_at IS NULL) = (decision_channel IS NULL)
            ),
            CONSTRAINT ck_automation_suggestions_decided_by
                CHECK (decided_by IS NULL OR decided_by IN ('you', 'claude', 'policy')),
            CONSTRAINT ck_automation_suggestions_decision_channel CHECK (
                decision_channel IS NULL
                OR decision_channel IN ('app', 'model', 'companion', 'policy')
            ),
            CONSTRAINT ck_automation_suggestions_policy_decision CHECK (
                (decided_by IS NOT DISTINCT FROM 'policy')
                = (decision_channel IS NOT DISTINCT FROM 'policy')
            ),
            CONSTRAINT ck_automation_suggestions_applied CHECK (
                (applied_kind IS NULL) = (applied_id IS NULL)
                AND (applied_kind IS NULL) = (applied_version IS NULL)
            ),
            CONSTRAINT ck_automation_suggestions_version CHECK (version >= 1),
            CONSTRAINT automation_suggestions_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_automation_suggestions_run_automation_owner
                FOREIGN KEY (run_id, automation_id, owner_id)
                REFERENCES sidekick.automation_runs(id, automation_id, owner_id)
                ON DELETE CASCADE
        );
        CREATE INDEX ix_automation_suggestions_owner_state
            ON sidekick.automation_suggestions USING btree (owner_id, state, bulk_eligible);
        CREATE INDEX ix_automation_suggestions_run
            ON sidekick.automation_suggestions USING btree (run_id);
        CREATE INDEX ix_automation_suggestions_pending_expiry
            ON sidekick.automation_suggestions USING btree (expires_at)
            WHERE state = 'pending';

        CREATE TABLE sidekick.automation_checks (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            suggestion_id uuid NOT NULL,
            run_id uuid NOT NULL,
            attempt integer NOT NULL,
            checker character varying(16) NOT NULL,
            model character varying(120) NOT NULL,
            verdict character varying(12) NOT NULL,
            confidence smallint,
            reason_codes character varying(32)[] DEFAULT '{}' NOT NULL,
            checked_at timestamp with time zone NOT NULL,
            CONSTRAINT automation_checks_pkey PRIMARY KEY (id),
            CONSTRAINT uq_automation_checks_suggestion_attempt UNIQUE (suggestion_id, attempt),
            CONSTRAINT ck_automation_checks_attempt CHECK (attempt >= 1),
            CONSTRAINT ck_automation_checks_checker
                CHECK (checker IN ('anthropic', 'openai_compat')),
            CONSTRAINT ck_automation_checks_verdict
                CHECK (verdict IN ('ok', 'uncertain', 'suspicious', 'error')),
            CONSTRAINT ck_automation_checks_confidence CHECK (
                confidence IS NULL OR (confidence BETWEEN 0 AND 100 AND verdict <> 'error')
            ),
            CONSTRAINT ck_automation_checks_reason_codes CHECK (
                reason_codes <@ ARRAY[
                    'out_of_scope', 'destructive_intent', 'instruction_like_text',
                    'mismatch_with_source', 'payment_related', 'contact_detail_unverified',
                    'duplicate_likely', 'other'
                ]::character varying[]
            ),
            CONSTRAINT automation_checks_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_automation_checks_suggestion_owner FOREIGN KEY (suggestion_id, owner_id)
                REFERENCES sidekick.automation_suggestions(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_automation_checks_run_owner FOREIGN KEY (run_id, owner_id)
                REFERENCES sidekick.automation_runs(id, owner_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_automation_checks_run
            ON sidekick.automation_checks USING btree (run_id);

        CREATE TABLE sidekick.automation_report_cursors (
            owner_id uuid NOT NULL,
            seen_until timestamp with time zone NOT NULL,
            version integer NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT automation_report_cursors_pkey PRIMARY KEY (owner_id),
            CONSTRAINT ck_automation_report_cursors_version CHECK (version >= 1),
            CONSTRAINT automation_report_cursors_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE
        );

        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.automations TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.automations FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.automation_runs TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.automation_runs FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.automation_datapoints TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.automation_datapoints FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.automation_suggestions TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.automation_suggestions FROM sidekick_app;
        GRANT SELECT, INSERT ON TABLE sidekick.automation_checks TO sidekick_app;
        REVOKE UPDATE, DELETE ON TABLE sidekick.automation_checks FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.automation_report_cursors TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.automation_report_cursors FROM sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.automation_report_cursors;
        DROP TABLE IF EXISTS sidekick.automation_checks;
        DROP TABLE IF EXISTS sidekick.automation_suggestions;
        DROP TABLE IF EXISTS sidekick.automation_datapoints;
        DROP TABLE IF EXISTS sidekick.automation_runs;
        DROP TABLE IF EXISTS sidekick.automations;
        """,
    )
]
