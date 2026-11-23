"""Add the tables for ready conversations: the owner's schedules and what was done with each day.

A ready conversation is a standing prompt the owner's Claude can offer on a schedule: a title, the
owner's own words for Claude (`instruction`), a closed list of what to read when it starts
(`ingredients`) and a `cadence` (a recurrence rule plus a `local_time` of day, shaped as in
`automations.cadence`). It is ready on a cadence day from that time until the end of the day, in
the owner's zone, unless that day was skipped or already started. Nothing a conversation will say
is stored: the summary is composed from the owner's records when the conversation is started.
A conversation is paused or archived, never erased.

`ready_conversation_days` holds one row per conversation and calendar day that was skipped, started
or reopened (`open`, the undo of a skip). It is transient: the application deletes rows older than
60 days when it writes one, which is why the runtime role may delete there and nowhere else.

Expand only: two new tables and nothing else; no existing data is touched. The runtime role may
read, insert and update the conversations but not delete them (the schema's default privileges
would also grant DELETE, so the migration takes it away), and may read, insert, update and delete
the day rows. A row leaves with its owner's account through the foreign keys, which the database
applies on its own. A day row names its conversation through `(conversation_id, owner_id)`, so it
belongs to the owner of that conversation and to no other. The rollback drops the two tables, which
loses only the schedules and their day marks.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"121_review"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;

        CREATE TABLE sidekick.ready_conversations (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            title character varying(80) NOT NULL,
            kind character varying(16) NOT NULL,
            instruction text,
            instruction_written_by character varying(8),
            instruction_edited_by_model boolean DEFAULT false NOT NULL,
            ingredients character varying(24)[] DEFAULT '{}' NOT NULL,
            cadence jsonb NOT NULL,
            state character varying(10) DEFAULT 'active' NOT NULL,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT ready_conversations_pkey PRIMARY KEY (id),
            CONSTRAINT uq_ready_conversations_id_owner UNIQUE (id, owner_id),
            CONSTRAINT ready_conversations_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT ck_ready_conversations_title
                CHECK (char_length(title) BETWEEN 1 AND 80),
            CONSTRAINT ck_ready_conversations_instruction_provenance CHECK (
                (instruction IS NULL AND instruction_written_by IS NULL
                    AND NOT instruction_edited_by_model)
                OR (instruction IS NOT NULL AND instruction_written_by IS NOT NULL
                    AND instruction_written_by IN ('you', 'claude'))
            ),
            CONSTRAINT ck_ready_conversations_kind CHECK (
                kind IN ('evening_review', 'morning_plan', 'weekly_review', 'custom')
            ),
            CONSTRAINT ck_ready_conversations_instruction
                CHECK (instruction IS NULL OR char_length(instruction) BETWEEN 1 AND 2000),
            CONSTRAINT ck_ready_conversations_ingredients CHECK (
                cardinality(ingredients) <= 10
                AND ingredients <@ ARRAY[
                    'tasks_done_today', 'tasks_due_today', 'tasks_due_tomorrow', 'overdue',
                    'waiting', 'suggestions', 'journal_today', 'review',
                    'automation_report', 'shopping_open'
                ]::character varying[]
            ),
            CONSTRAINT ck_ready_conversations_cadence CHECK (
                jsonb_typeof(cadence) = 'object' AND octet_length(cadence::text) <= 2048
            ),
            CONSTRAINT ck_ready_conversations_state
                CHECK (state IN ('active', 'paused', 'archived')),
            CONSTRAINT ck_ready_conversations_version CHECK (version >= 1)
        );
        CREATE INDEX ix_ready_conversations_owner_state
            ON sidekick.ready_conversations USING btree (owner_id, state);

        CREATE TABLE sidekick.ready_conversation_days (
            conversation_id uuid NOT NULL,
            day date NOT NULL,
            owner_id uuid NOT NULL,
            state character varying(8) NOT NULL,
            changed_at timestamp with time zone NOT NULL,
            version integer NOT NULL,
            CONSTRAINT ready_conversation_days_pkey PRIMARY KEY (conversation_id, day),
            CONSTRAINT ready_conversation_days_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_ready_conversation_days_conversation_owner
                FOREIGN KEY (conversation_id, owner_id)
                REFERENCES sidekick.ready_conversations(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT ck_ready_conversation_days_state
                CHECK (state IN ('skipped', 'started', 'open')),
            CONSTRAINT ck_ready_conversation_days_version CHECK (version >= 1)
        );
        CREATE INDEX ix_ready_conversation_days_owner_day
            ON sidekick.ready_conversation_days USING btree (owner_id, day);

        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.ready_conversations TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.ready_conversations FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE sidekick.ready_conversation_days
            TO sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.ready_conversation_days;
        DROP TABLE IF EXISTS sidekick.ready_conversations;
        """,
    )
]
