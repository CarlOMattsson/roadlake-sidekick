# Connect Claude

[Svenska](connect-claude.sv.md)

<!-- description: Add your server as a custom connector in Claude and sign in with GitHub. This is also where you decide which scopes the session gets, and how to remove access. -->

Add your server as a custom connector in Claude and sign in with GitHub. This is also where you decide which scopes the session gets, and how to remove access.

Claude signs in to your server through GitHub, but Sidekick decides who gets in: only the GitHub accounts listed in
`SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES`.

**Register a GitHub OAuth app** (GitHub, Settings, Developer settings, OAuth Apps, New OAuth App):

- Homepage URL: `https://<your-domain>`
- Authorization callback URL: `https://<your-domain>/mcp/auth/callback`
- Generate a client secret. Put the Client ID and the secret in `SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_ID` and
  `SIDEKICK_MCP_OAUTH_GITHUB_CLIENT_SECRET`. Sidekick asks GitHub for no permissions beyond who you are.

**Add the connector in Claude.** The server address is `https://<your-domain>/mcp` (no trailing slash, the same host
as `SIDEKICK_MCP_PUBLIC_BASE_URL`). In Claude, open Settings, Connectors and choose to add a custom connector (menu
names vary with the Claude version and plan; on Team and Enterprise plans an organisation owner adds it first; see
[Anthropic's guide to custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp)).
Give it a name such as "Sidekick" and paste the address. Do not enter an OAuth client id or secret under Advanced
settings: Claude registers itself with the server. By default only Claude's own callback
(`https://claude.ai/api/mcp/auth_callback`) is accepted as a redirect.

**First sign-in.** Choose Connect. Claude opens your server's consent page, which asks you to approve the connection;
approve it, then sign in with the GitHub account whose id you listed. You land back in Claude with the connector
connected. A GitHub account that is not listed is refused after the sign-in. To check, ask Claude for something Sidekick
holds, for example "What are my open tasks?".

**What the session may do.** Exactly the scopes in `SIDEKICK_MCP_OAUTH_SCOPES`, whatever the client asks for and
whatever GitHub says. The example ships with read scopes for projects, tasks, contacts and shopping only: Claude can
read those, cannot change anything, and has no access to the Journal. Add `journal:read` for the Journal; a `:write`
scope (listed next to its `:read`, for example `projects:write,projects:read`) lets Claude change that data, and
`license:write` lets the app enter the instance's license key (add it only if you enter the key in the app), and
`automation:read` / `automation:write` are reserved: no tool uses them yet. Widen the list deliberately, then recreate the API (`docker compose --env-file selfhost.env up -d --force-recreate api`). If Claude
does not pick up the change, remove the connector and add it again.

**Slow clients.** The API gives a public request one deadline for its whole body to arrive, so a client that drips
bytes gets `408 Request Timeout` instead of holding a worker: `SIDEKICK_BODY_READ_TIMEOUT_SECONDS` (default 30) for
requests in general and the shorter `SIDEKICK_OAUTH_BODY_READ_TIMEOUT_SECONDS` (default 10) for the OAuth forms. Both
are in seconds, above 0 and at most 300, and are commented out in `selfhost.env.example`. Raise one only if a legitimate
client on a very slow link is refused, then recreate the API.

**Overload and guessed tokens.** Two in-memory limits protect the API from clients that cost it more than they cost
the sender. Request bodies are held in memory until complete; at most `SIDEKICK_MAX_BUFFERED_REQUESTS` (default 32,
1 to 1024, up to 1 MiB each) may still be arriving at once, and a request that finds every slot taken gets `503` with
`Retry-After: 1`. A slot is freed when the body is complete, not when the request has been answered, because an MCP
answer can stay open for a long time. A quarter of the slots is held back for bearer tokens the API has verified within the
last hour, so anonymous clients that open many slow bodies cannot starve your connected clients. Checking a bearer token costs a database query, so failed attempts (answered 401)
are counted in a sliding minute: after `SIDEKICK_FAILED_AUTH_PER_CLIENT_PER_MINUTE` (default 10) from one client
address, or `SIDEKICK_FAILED_AUTH_GLOBAL_PER_MINUTE` (default 60) from all clients together, further requests carrying
an unknown token get `429` with `Retry-After` before the database is touched. A token the API has verified within the
last hour is never throttled (the hour renews on every use), so your connected clients keep working during an attack.
`SIDEKICK_FAILED_AUTH_RESERVE_PER_MINUTE` (default 5, 0 turns it off) lets that many unknown-token requests per minute
through regardless, so your first valid call after an API restart, or after an hour of silence, reaches the API within
seconds even during a sustained attack (an attacker can use the reserve up, so a client may need a few retries).
Behind a tunnel such as Tailscale Funnel every visitor shares one address and no forwarded header is trusted, so the
per-client limit then equals the global one and the global limit and the reserve are what protect you. Because a
spent budget answers `429` for unknown tokens but `401` or success for known ones, a client can tell a recently used
token from a guess; this is harmless for the 256-bit random tokens Sidekick issues. All four settings are commented out
in `selfhost.env.example`; lower them only if you want a tighter guard, and raise them if many legitimate clients mistype
tokens at once.

**Remove access.**

- One person: delete their entry from `SIDEKICK_MCP_OAUTH_ALLOWED_IDENTITIES` and recreate the API as above. Their
  sessions stop working then, not only when they expire. The API remembers a successful GitHub check for
  `SIDEKICK_MCP_OAUTH_UPSTREAM_CACHE_SECONDS` (default 300, five minutes; at most 3600; `0` asks GitHub on every request), and
  recreating the container clears that memory.
- Cut a person off at once, and for good: `docker compose --env-file selfhost.env run --rm -T api sidekick-admin disable-user --user-id <UUID>`.
  Unlike the steps above it is checked on every request. Recreating the API alone is not enough to lock anyone out: a
  person who is still listed and whose GitHub sign-in is still valid is accepted again. To make a revoked GitHub
  authorisation count immediately, revoke it on GitHub (below) and recreate the API, which empties the memory of earlier
  GitHub checks:

  ```bash
  docker compose --env-file selfhost.env up -d --force-recreate api
  ```

- Every session at once: change `SIDEKICK_MCP_OAUTH_SIGNING_KEY` and recreate the API. Every client has to sign in again.
- Also delete the connector in Claude, and on GitHub revoke the OAuth app under Settings, Applications, Authorized
  OAuth Apps.
- Personal access tokens do not apply to this stack. This guide runs `SIDEKICK_MCP_AUTH_MODE=github_oauth`, and in that
  mode `/mcp` accepts only the GitHub sign-in described above: a token from `sidekick-admin create-token` is refused with
  `401 invalid_token`, and there is no fallback. Tokens work only in `SIDEKICK_MCP_AUTH_MODE=pat`, the local developer
  mode ([QUICKSTART.md](../../QUICKSTART.md)), where there is no GitHub sign-in. Which mode is active is decided by
  that one setting; the other mode's credentials never work. `sidekick-admin list-tokens --user-id <UUID>` and
  `revoke-token --token-id <ID>` (run like the commands above) manage tokens in developer mode.
