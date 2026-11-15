"""Let the owner give a home-automation or phone-automation tool a token of its own.

`webhook_tokens` holds one row per integration (Home Assistant, Tasker, ...). A token is shown once
when the operator creates it; only its keyed digest and a short prefix, which the operator's list
uses to tell tokens apart, are stored. Each token carries its own closed set of webhook scopes
(`webhook:shopping:add`, `webhook:tasks:create`), a rate limit per minute, a required expiry and
a revocation time. The rows are separate from `personal_access_tokens`: a webhook token is accepted
only by `/webhooks/v1/`, and no MCP or companion credential is accepted there.

Expand only: one new table. The runtime role may read, insert and update it (a revocation and the
last-used time are updates); it can delete nothing (the schema's default privileges would also
grant DELETE, so the migration takes it away), and no DDL. The rollback drops the table, which
revokes every webhook token and loses nothing else.
"""

# migration-class: expand

from yoyo import step

__depends__ = {"110_task_ambition"}

steps = [
    step(
        """
        SET LOCAL ROLE sidekick_owner;
        CREATE TABLE sidekick.webhook_tokens (
            id uuid NOT NULL,
            user_id uuid NOT NULL,
            label character varying(120) NOT NULL,
            token_prefix character varying(12) NOT NULL,
            token_digest character(64) NOT NULL,
            scopes jsonb NOT NULL,
            rate_limit_per_minute integer NOT NULL,
            expires_at timestamp with time zone NOT NULL,
            revoked_at timestamp with time zone,
            last_used_at timestamp with time zone,
            created_at timestamp with time zone NOT NULL,
            CONSTRAINT webhook_tokens_pkey PRIMARY KEY (id),
            CONSTRAINT webhook_tokens_token_digest_key UNIQUE (token_digest),
            CONSTRAINT ck_webhook_tokens_rate
                CHECK (rate_limit_per_minute BETWEEN 1 AND 600),
            CONSTRAINT ck_webhook_tokens_scopes
                CHECK (jsonb_typeof(scopes) = 'array' AND jsonb_array_length(scopes) > 0),
            CONSTRAINT ck_webhook_tokens_expiry CHECK (expires_at > created_at),
            CONSTRAINT webhook_tokens_user_id_fkey FOREIGN KEY (user_id)
                REFERENCES sidekick.users(id) ON DELETE CASCADE
        );
        CREATE INDEX ix_webhook_tokens_user
            ON sidekick.webhook_tokens USING btree (user_id, created_at);
        GRANT SELECT, INSERT, UPDATE ON TABLE sidekick.webhook_tokens TO sidekick_app;
        REVOKE DELETE ON TABLE sidekick.webhook_tokens FROM sidekick_app;
        """,
        """
        SET LOCAL ROLE sidekick_owner;
        DROP TABLE IF EXISTS sidekick.webhook_tokens;
        """,
    )
]
