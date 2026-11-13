"""Let Contacts and Journal entries carry tags from the same vocabulary as Tasks.

`work_tags` is the owner's one tag vocabulary. Domains, Processes, Projects and Tasks already link
to it through narrow per-kind tables; this adds the same two tables for Contacts and Journal
entries (`contact_tags`, `journal_entry_tags`), shaped exactly like `task_tags`: a composite key of
owner, tag and record, composite owner-consistent foreign keys to both sides (a link can only join
two records of one owner), a reverse index for the per-record read, and the app role's table
privileges.

Expand only: two new tables, nothing existing is changed and no row is moved. The rollback drops
them, which discards the links made since, never a tag or a record.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"106_drop_retired_automation_tables"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE TABLE sidekick.contact_tags (
            owner_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            contact_id uuid NOT NULL,
            created_at timestamp with time zone NOT NULL,
            CONSTRAINT contact_tags_pkey PRIMARY KEY (owner_id, tag_id, contact_id),
            CONSTRAINT contact_tags_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_contact_tags_tag_owner FOREIGN KEY (tag_id, owner_id)
                REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_contact_tags_target_owner FOREIGN KEY (contact_id, owner_id)
                REFERENCES sidekick.contacts(id, owner_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_contact_tags_reverse
            ON sidekick.contact_tags USING btree (owner_id, contact_id, tag_id);
        GRANT SELECT, INSERT, DELETE, UPDATE ON TABLE sidekick.contact_tags TO sidekick_app;
        CREATE TABLE sidekick.journal_entry_tags (
            owner_id uuid NOT NULL,
            tag_id uuid NOT NULL,
            journal_entry_id uuid NOT NULL,
            created_at timestamp with time zone NOT NULL,
            CONSTRAINT journal_entry_tags_pkey PRIMARY KEY (owner_id, tag_id, journal_entry_id),
            CONSTRAINT journal_entry_tags_owner_id_fkey FOREIGN KEY (owner_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE,
            CONSTRAINT fk_journal_entry_tags_tag_owner FOREIGN KEY (tag_id, owner_id)
                REFERENCES sidekick.work_tags(id, owner_id) ON DELETE CASCADE,
            CONSTRAINT fk_journal_entry_tags_target_owner FOREIGN KEY (journal_entry_id, owner_id)
                REFERENCES sidekick.journal_entries(id, owner_id) ON DELETE CASCADE
        );
        CREATE INDEX ix_journal_entry_tags_reverse
            ON sidekick.journal_entry_tags USING btree (owner_id, journal_entry_id, tag_id);
        GRANT SELECT, INSERT, DELETE, UPDATE ON TABLE sidekick.journal_entry_tags TO sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.journal_entry_tags;
        DROP TABLE IF EXISTS sidekick.contact_tags;
        """,
    )
]
