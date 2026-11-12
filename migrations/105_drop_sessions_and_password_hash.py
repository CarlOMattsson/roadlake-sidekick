"""Drop the browser sign-in remnants: the `sessions` table and the `users.password_hash` column.

The web sign-in was removed with D-082, and nothing reads or writes either object any more. Access
is an MCP personal token, a companion device credential or the GitHub OAuth identity mapping, so no
password is ever checked. The runtime stopped mapping `sessions` then, and it no longer writes a
`users.password_hash` value, so both can go.

This is destructive: it deletes any rows still in `sessions` (expired browser sessions, which no
code can use) and the stored password hashes (which nothing verifies). The 0.1.0 baseline is left
untouched because installations have already applied it. `sidekick_app` loses its grants on
`sessions` together with the table; the grants on `users` are table-wide and stay as they are.

Downgrade recreates the table with its constraints and grants, empty, and the column with an empty
string for every existing user (the column is NOT NULL), so the pre-105 code can run again. The
old values cannot be restored.
"""

# migration-class: contract
# DROP TABLE and DROP COLUMN remove data, which the migration policy treats as a contract step.

from yoyo import step

__depends__ = {"104_audit_event_source"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE sidekick.sessions;
        ALTER TABLE sidekick.users DROP COLUMN password_hash;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        ALTER TABLE sidekick.users ADD COLUMN password_hash text NOT NULL DEFAULT '';
        ALTER TABLE sidekick.users ALTER COLUMN password_hash DROP DEFAULT;
        CREATE TABLE sidekick.sessions (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            token_digest character(64) NOT NULL,
            csrf_digest character(64) NOT NULL,
            expires_at timestamp with time zone NOT NULL,
            revoked_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL
        );
        ALTER TABLE ONLY sidekick.sessions
            ADD CONSTRAINT sessions_pkey PRIMARY KEY (id);
        ALTER TABLE ONLY sidekick.sessions
            ADD CONSTRAINT sessions_token_digest_key UNIQUE (token_digest);
        ALTER TABLE ONLY sidekick.sessions
            ADD CONSTRAINT sessions_user_id_fkey
            FOREIGN KEY (user_id) REFERENCES sidekick.users(id) ON DELETE CASCADE;
        GRANT SELECT,INSERT,DELETE,UPDATE ON TABLE sidekick.sessions TO sidekick_app;
        """,
    )
]
