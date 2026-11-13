"""Let the owner ask Sidekick to stop using one remembered fact, without storing the fact.

Hindsight rebuilds every fact of a record whenever the record is sent again, so hiding a fact once
does not keep it hidden. Two new tables hold what is needed to hide it again:

- `memory_forgotten_facts`: one row per forgotten statement of an owner. `text_key` is a salted
  digest of the normalised statement. There is no text column: the table can say that a statement
  was forgotten, never what it said. `released_at` is NULL while the statement is forgotten.
- `memory_forgotten_units`: the provider-side fact ids that currently carry a forgotten statement,
  and the state of hiding them at the provider. It is also the reconcile pass's work queue, so the
  pass stays the only writer to the provider. A unit belongs to the same owner as its statement and
  its source row (composite foreign keys).

`memory_settings.forget_salt` is the owner's salt for the digest: 16 random bytes as 32 lower-case
hex characters, created at the first forgotten statement and NULL until then. It is kept apart from
the id-derivation key so rotating that key never makes a forgotten statement visible again.

`memory_sources` gets a unique key on (id, owner_id) so a unit, and a statement's origin, can only
point at its owner's source row (deleting the source row clears only `origin_source_id`). Expand only: nothing existing is changed and no row is moved. The rollback drops the two tables
and the new column and key, which discards every forgotten statement made since; no record, source
row or setting is touched.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"107_contact_and_journal_entry_tags"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.memory_settings ADD COLUMN forget_salt character(32);
        ALTER TABLE sidekick.memory_settings ADD CONSTRAINT ck_memory_settings_forget_salt
            CHECK (forget_salt IS NULL OR forget_salt ~ '^[0-9a-f]{32}$');
        ALTER TABLE sidekick.memory_sources
            ADD CONSTRAINT uq_memory_sources_id_owner UNIQUE (id, owner_id);
        CREATE TABLE sidekick.memory_forgotten_facts (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            text_key character(64) NOT NULL,
            created_at timestamp with time zone NOT NULL,
            released_at timestamp with time zone,
            origin_source_id uuid,
            CONSTRAINT memory_forgotten_facts_pkey PRIMARY KEY (id),
            CONSTRAINT uq_memory_forgotten_facts_id_owner UNIQUE (id, owner_id),
            CONSTRAINT uq_memory_forgotten_facts_key UNIQUE (owner_id, text_key),
            CONSTRAINT ck_memory_forgotten_facts_text_key CHECK (text_key ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_memory_forgotten_facts_released
                CHECK (released_at IS NULL OR released_at >= created_at),
            CONSTRAINT memory_forgotten_facts_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_memory_forgotten_facts_origin_owner
                FOREIGN KEY (origin_source_id, owner_id)
                REFERENCES sidekick.memory_sources(id, owner_id)
                ON DELETE SET NULL (origin_source_id)
        );
        GRANT SELECT, INSERT, DELETE, UPDATE ON TABLE sidekick.memory_forgotten_facts
            TO sidekick_app;
        CREATE TABLE sidekick.memory_forgotten_units (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            forgotten_id uuid NOT NULL,
            memory_source_id uuid NOT NULL,
            provider_fact_id character varying(200) NOT NULL,
            state character varying(12) NOT NULL,
            attempts integer DEFAULT 0 NOT NULL,
            next_attempt_at timestamp with time zone,
            failure_category character varying(40),
            CONSTRAINT memory_forgotten_units_pkey PRIMARY KEY (id),
            CONSTRAINT uq_memory_forgotten_units_fact
                UNIQUE (memory_source_id, provider_fact_id),
            CONSTRAINT ck_memory_forgotten_units_provider_fact_id
                CHECK (length(btrim(provider_fact_id)) > 0),
            CONSTRAINT ck_memory_forgotten_units_state
                CHECK (state IN ('pending', 'invalidated', 'reverting', 'parked')),
            CONSTRAINT ck_memory_forgotten_units_attempts CHECK (attempts >= 0),
            CONSTRAINT ck_memory_forgotten_units_parked
                CHECK (state <> 'parked' OR failure_category IS NOT NULL),
            CONSTRAINT fk_memory_forgotten_units_fact_owner FOREIGN KEY (forgotten_id, owner_id)
                REFERENCES sidekick.memory_forgotten_facts(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_memory_forgotten_units_source_owner
                FOREIGN KEY (memory_source_id, owner_id)
                REFERENCES sidekick.memory_sources(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT memory_forgotten_units_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE
        );
        CREATE INDEX ix_memory_forgotten_units_due
            ON sidekick.memory_forgotten_units USING btree (state, next_attempt_at, id);
        CREATE INDEX ix_memory_forgotten_units_fact
            ON sidekick.memory_forgotten_units USING btree (forgotten_id);
        GRANT SELECT, INSERT, DELETE, UPDATE ON TABLE sidekick.memory_forgotten_units
            TO sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.memory_forgotten_units;
        DROP TABLE IF EXISTS sidekick.memory_forgotten_facts;
        ALTER TABLE sidekick.memory_sources DROP CONSTRAINT IF EXISTS uq_memory_sources_id_owner;
        ALTER TABLE sidekick.memory_settings
            DROP CONSTRAINT IF EXISTS ck_memory_settings_forget_salt;
        ALTER TABLE sidekick.memory_settings DROP COLUMN IF EXISTS forget_salt;
        """,
    )
]
