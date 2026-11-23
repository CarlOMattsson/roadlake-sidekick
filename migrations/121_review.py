"""Add the tables for repetition: the owner's settings, the cards and the log of answers.

`review_cards` holds one card per thing to remember: a contact (face to name) or a library fact.
A card keeps no copy of what it asks about; the front and the back are read from the source when
shown, so a corrected name is right on the next card and an erased contact takes its card with it
through the foreign key. Exactly the key that matches `source_kind` is set, and a source has at
most one card. A card also holds its schedule (`fsrs_state`, `step`, `stability`, `difficulty`,
`due_at`, `last_review_at`, `reps`, `lapses`), which is only a cache: it is what folding the log of
the card gives, and `scheduler_version` names the rules that folded it.

`review_log` is the authority: one row per answer, written once and never changed. `rating` is
1 to 4 on the FSRS scale (version 1 writes 1 and 3), `reviewed_at` is the moment the owner answered
(the client's clock, clamped by the application), `received_at` the server's, and
`client_review_id` is the idempotency key of the answer, so a replay from a phone that was offline
writes nothing twice. `review_settings` holds one row per owner, written on first use. Review is
off until the owner turns it on.

`review_cards.library_fact_id` names a library fact, but the table of library facts does not exist
yet, so the column carries no foreign key here; the migration that creates that table adds it.

Expand only: three new tables and nothing else; no existing data is touched. The runtime role may
read, insert and update the settings, read, insert, update and delete cards, and only read and
insert log rows (the schema's default privileges would also grant UPDATE and DELETE on the log, so
the migration takes them away). A log row leaves with its card, or with the owner's account,
through the foreign keys, which the database applies on its own. The rollback drops the three
tables, which loses only the repetition data.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"124_journal_attachment_details"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;

        CREATE TABLE sidekick.review_settings (
            owner_id uuid NOT NULL,
            enabled boolean DEFAULT false NOT NULL,
            include_contacts boolean DEFAULT true NOT NULL,
            include_library boolean DEFAULT true NOT NULL,
            new_per_day smallint DEFAULT 10 NOT NULL,
            max_reviews_per_day smallint DEFAULT 200 NOT NULL,
            push_enabled boolean DEFAULT true NOT NULL,
            push_local_time time without time zone DEFAULT '18:00' NOT NULL,
            desired_retention numeric(3,2) DEFAULT 0.90 NOT NULL,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT review_settings_pkey PRIMARY KEY (owner_id),
            CONSTRAINT review_settings_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT ck_review_settings_new_per_day CHECK (new_per_day BETWEEN 0 AND 50),
            CONSTRAINT ck_review_settings_max_reviews_per_day
                CHECK (max_reviews_per_day BETWEEN 10 AND 1000),
            CONSTRAINT ck_review_settings_desired_retention
                CHECK (desired_retention BETWEEN 0.80 AND 0.97),
            CONSTRAINT ck_review_settings_version CHECK (version >= 1)
        );

        CREATE TABLE sidekick.review_cards (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            source_kind character varying(16) NOT NULL,
            contact_id uuid,
            library_fact_id uuid,
            fsrs_state character varying(10) DEFAULT 'new' NOT NULL,
            step smallint,
            stability double precision,
            difficulty double precision,
            due_at timestamp with time zone,
            last_review_at timestamp with time zone,
            reps integer DEFAULT 0 NOT NULL,
            lapses integer DEFAULT 0 NOT NULL,
            introduced_on date,
            suspended_at timestamp with time zone,
            retired_at timestamp with time zone,
            scheduler_version character varying(40) NOT NULL,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            CONSTRAINT review_cards_pkey PRIMARY KEY (id),
            CONSTRAINT uq_review_cards_id_owner UNIQUE (id, owner_id),
            CONSTRAINT review_cards_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_review_cards_contact_owner FOREIGN KEY (contact_id, owner_id)
                REFERENCES sidekick.contacts(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT ck_review_cards_source CHECK (
                (source_kind = 'contact_face'
                    AND contact_id IS NOT NULL AND library_fact_id IS NULL)
                OR (source_kind = 'library_fact'
                    AND library_fact_id IS NOT NULL AND contact_id IS NULL)
            ),
            CONSTRAINT ck_review_cards_fsrs_state
                CHECK (fsrs_state IN ('new', 'learning', 'review', 'relearning')),
            CONSTRAINT ck_review_cards_schedule CHECK (
                (fsrs_state = 'new' AND due_at IS NULL AND stability IS NULL
                    AND difficulty IS NULL AND step IS NULL)
                OR (fsrs_state <> 'new' AND due_at IS NOT NULL)
            ),
            CONSTRAINT ck_review_cards_step CHECK (step IS NULL OR step >= 0),
            CONSTRAINT ck_review_cards_counts CHECK (reps >= 0 AND lapses >= 0),
            CONSTRAINT ck_review_cards_version CHECK (version >= 1)
        );
        CREATE UNIQUE INDEX uq_review_cards_contact
            ON sidekick.review_cards USING btree (owner_id, contact_id)
            WHERE contact_id IS NOT NULL;
        CREATE UNIQUE INDEX uq_review_cards_library_fact
            ON sidekick.review_cards USING btree (owner_id, library_fact_id)
            WHERE library_fact_id IS NOT NULL;
        CREATE INDEX ix_review_cards_due
            ON sidekick.review_cards USING btree (owner_id, due_at)
            WHERE due_at IS NOT NULL AND suspended_at IS NULL AND retired_at IS NULL;
        CREATE INDEX ix_review_cards_new
            ON sidekick.review_cards USING btree (owner_id, created_at, id)
            WHERE fsrs_state = 'new' AND suspended_at IS NULL AND retired_at IS NULL;

        CREATE TABLE sidekick.review_log (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            card_id uuid NOT NULL,
            rating smallint NOT NULL,
            reviewed_at timestamp with time zone NOT NULL,
            received_at timestamp with time zone NOT NULL,
            client_review_id character varying(64) NOT NULL,
            channel character varying(10) NOT NULL,
            duration_ms integer,
            clock_adjusted boolean DEFAULT false NOT NULL,
            CONSTRAINT review_log_pkey PRIMARY KEY (id),
            CONSTRAINT review_log_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_review_log_card_owner FOREIGN KEY (card_id, owner_id)
                REFERENCES sidekick.review_cards(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT uq_review_log_card_client_review UNIQUE (card_id, client_review_id),
            CONSTRAINT ck_review_log_rating CHECK (rating BETWEEN 1 AND 4),
            CONSTRAINT ck_review_log_channel CHECK (channel IN ('app', 'companion')),
            CONSTRAINT ck_review_log_duration
                CHECK (duration_ms IS NULL OR duration_ms BETWEEN 0 AND 600000),
            CONSTRAINT ck_review_log_client_review_id
                CHECK (char_length(client_review_id) BETWEEN 1 AND 64)
        );
        CREATE INDEX ix_review_log_owner_reviewed
            ON sidekick.review_log USING btree (owner_id, reviewed_at);
        CREATE INDEX ix_review_log_card_reviewed
            ON sidekick.review_log USING btree (card_id, reviewed_at);

        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.review_settings TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.review_settings FROM sidekick_app;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE sidekick.review_cards TO sidekick_app;
        GRANT SELECT, INSERT ON TABLE sidekick.review_log TO sidekick_app;
        REVOKE UPDATE, DELETE ON TABLE sidekick.review_log FROM sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.review_log;
        DROP TABLE IF EXISTS sidekick.review_cards;
        DROP TABLE IF EXISTS sidekick.review_settings;
        """,
    )
]
