"""Let a Journal entry or a Journal day carry photos: the metadata of each photo.

`journal_attachments` holds one row per photo. The bytes are not here; the row names them by the
SHA-256 digest of the stored file (`content_digest`) and of its thumbnail (`thumb_digest`). A
photo belongs either to a Journal entry (`entry_id`) or to a day (`journal_date`), never to both
and never to neither. The size, the dimensions and the type are bounded by CHECK constraints, so
the database refuses a row the application should never write. A photo carries no location: the
only time it may hold is `taken_at`, and only when the client sent it. Alt text is the owner's
text, with `alt_text_by` saying whether the owner or Claude wrote it.

Unlike a Journal entry, a photo can be erased: the runtime role may read, insert, update and delete
the rows (the schema's default privileges grant this; the migration states it so the grant does not
depend on them). A photo is trashed first (`trashed_at`) and only a trashed photo is erased. A row
leaves with its entry or owner when that is removed, through the foreign keys.

Expand only: one new table with its indexes. The rollback drops the table, which loses only the
photo metadata entered since.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"116_automations"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE TABLE sidekick.journal_attachments (
            id uuid NOT NULL,
            owner_id uuid NOT NULL,
            entry_id uuid,
            journal_date date,
            media_type character varying(16) NOT NULL,
            byte_size integer NOT NULL,
            width smallint NOT NULL,
            height smallint NOT NULL,
            content_digest character(64) NOT NULL,
            thumb_digest character(64) NOT NULL,
            thumb_size integer NOT NULL,
            alt_text character varying(500),
            alt_text_by character varying(8),
            taken_at timestamp with time zone,
            "position" smallint NOT NULL,
            version integer NOT NULL,
            created_at timestamp with time zone NOT NULL,
            updated_at timestamp with time zone NOT NULL,
            trashed_at timestamp with time zone,
            CONSTRAINT journal_attachments_pkey PRIMARY KEY (id),
            CONSTRAINT uq_journal_attachments_id_owner UNIQUE (id, owner_id),
            CONSTRAINT journal_attachments_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_journal_attachments_entry_owner FOREIGN KEY (entry_id, owner_id)
                REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT ck_journal_attachments_target
                CHECK ((entry_id IS NULL) <> (journal_date IS NULL)),
            CONSTRAINT ck_journal_attachments_media_type
                CHECK (media_type IN ('image/jpeg', 'image/webp')),
            CONSTRAINT ck_journal_attachments_byte_size
                CHECK (byte_size BETWEEN 1 AND 4194304),
            CONSTRAINT ck_journal_attachments_dimensions
                CHECK (width BETWEEN 1 AND 4096 AND height BETWEEN 1 AND 4096),
            CONSTRAINT ck_journal_attachments_content_digest
                CHECK (content_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_journal_attachments_thumb_digest
                CHECK (thumb_digest ~ '^[0-9a-f]{64}$'),
            CONSTRAINT ck_journal_attachments_thumb_size
                CHECK (thumb_size BETWEEN 1 AND 131072),
            CONSTRAINT ck_journal_attachments_alt_text
                CHECK (alt_text IS NULL OR length(btrim(alt_text)) > 0),
            CONSTRAINT ck_journal_attachments_alt_text_by CHECK (
                (alt_text IS NULL AND alt_text_by IS NULL)
                OR (alt_text IS NOT NULL AND alt_text_by IS NOT NULL
                    AND alt_text_by IN ('you', 'claude'))
            ),
            CONSTRAINT ck_journal_attachments_position CHECK ("position" >= 0),
            CONSTRAINT ck_journal_attachments_version CHECK (version >= 1)
        );
        CREATE INDEX ix_journal_attachments_entry
            ON sidekick.journal_attachments USING btree (owner_id, entry_id, "position")
            WHERE entry_id IS NOT NULL;
        CREATE INDEX ix_journal_attachments_day
            ON sidekick.journal_attachments USING btree (owner_id, journal_date, "position")
            WHERE journal_date IS NOT NULL;
        CREATE INDEX ix_journal_attachments_digest
            ON sidekick.journal_attachments USING btree (owner_id, content_digest);
        CREATE INDEX ix_journal_attachments_trashed
            ON sidekick.journal_attachments USING btree (owner_id, trashed_at)
            WHERE trashed_at IS NOT NULL;
        GRANT SELECT, INSERT, UPDATE, DELETE ON TABLE sidekick.journal_attachments TO sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.journal_attachments;
        """,
    )
]
