# ADR-007: Authenticate with purpose-separated, hashed credentials and enforce scopes in the use cases

- Status: Accepted (D-090, 2026-11-11); records the delivered design, no behaviour changed
- Date: 2026-11-11
- Owners: Sidekick application maintainers

## Context

Sidekick serves one owner over two public surfaces: the MCP endpoint that Claude uses, and the companion adapter
that the Android app uses (ADR-002, ADR-005). There is no web sign-in, no session and no cookie. Whoever holds a
credential acts as the owner within the credential's scopes, and the host model that calls the tools is not trusted
to decide what it may do. The design had to keep a stolen phone credential from working as an MCP token (and the
reverse), keep a database leak from yielding usable credentials, and make "which scope does this call need" a
property of the server rather than of a tool description.

## Decision

### Three ways in, one verified actor

- **Personal access token** (`rsp_` prefix). Created by the operator with `sidekick-admin`, shown once, scoped,
  expiring (90 days by default, at most 365, or explicitly never) and revocable
  (`backend/src/sidekick/admin/cli.py`, `AuthService.create_personal_token`).
- **GitHub OAuth** for the public MCP endpoint (`SIDEKICK_MCP_AUTH_MODE=github_oauth`). Sidekick writes no
  authorization server: FastMCP's OAuth proxy does registration, PKCE, audience and consent
  (`backend/src/sidekick/mcp/oauth.py`). Sidekick decides only whether the numeric GitHub id is on the configured
  allowlist and maps it to a local active user; the scopes are server policy, never the upstream grant and never what
  the client asked for (`GitHubIdentityVerifier`, `backend/src/sidekick/mcp/auth.py`). Nothing from the GitHub profile
  is carried into the request.
- **Companion device credential** (`rsc_` prefix), obtained by pairing and renewed by the device itself
  (`backend/src/sidekick/companion/service.py`; the threat model describes both flows).

Each verifier yields the same `Actor` (user id and a frozenset of scopes, `backend/src/sidekick/shared/types/core.py`),
resolved at the transport boundary. Use cases receive that actor and never accept an owner id from user-controlled
text as authority.

### Credentials are stored as keyed digests with a purpose

Tokens are stored only as HMAC-SHA256 digests under a server pepper (`AuthService.digest`); production refuses to
start with a missing or placeholder pepper (`backend/src/sidekick/shared/config/signing.py`). Sidekick stores no passwords:
a user has none (migration 105 dropped `users.password_hash` and the unused `sessions` table, and the `pwdlib`
dependency went with them). A credential row carries a `purpose` column (`mcp` or `companion`), and each
verifier selects on it, so neither can accept the other's rows by mistake; the column is not a prefix or a scope
convention. Every verification re-checks revocation, expiry and that the user is active, and `last_used_at` is
rewritten at most once a minute.

### Scopes: a closed vocabulary, clipped at verification, checked in the use case

- MCP scopes are twelve `<domain>:read|write` names and `license:write` (`MCP_SCOPES`). `license:write` is the one
  administrative scope: it alone allows the app-only `set_license_key` tool, so a client that only changes tasks cannot
  set the instance's license key. `automation:read` and `automation:write` are
  opt-in: a default token never has them (`OPT_IN_SCOPES`, `TOKEN_SCOPES`).
- Device scopes are a separate vocabulary (`COMPANION_SCOPES`, `companion:*`). No MCP credential can hold one and a
  device holds nothing else, so a paired phone is never handed `tasks:write` itself; the companion adapter maps each
  capability to a fixed set of operations (`backend/src/sidekick/companion/operations.py`).
- On verification the stored scopes are intersected with what the credential kind may hold, so a name that the code
  no longer defines is dropped rather than carried on (`verify_personal_token`, `verify_companion_token`).
- Services call `actor.require(scope)` before work and filter every read and write by `owner_id`
  (`docs/explanation/architecture/backend.md`). Transports do not check scopes for the application. A tool that answers with a
  part it needs a second scope for checks that scope before writing.
- Memory has no scope of its own; it reuses the read and write scopes of the domain it touches (ADR-008).

### Guards that keep this honest

`backend/tests/contract/test_mcp_tool_scope_gate.py` lists the tools from the running server, so a tool added later is
covered at once: with no scope every tool answers `forbidden`, with all scopes none does. "Ask first" wording in a
tool description is advice to the model, not an authorization; the server check is.

## Consequences

- Revoking a credential or disabling a user takes effect on the next call, except for the bounded windows stated
  where they are granted (the renewal grace of a device credential; the cache of the GitHub token check, five minutes
  by default, while the active-user check runs on every request).
- A new scope or tool needs an entry in the vocabulary, the use-case check, the contract snapshot and a gate test.
- A prompt-injected model can use whatever scopes its credential holds. Narrow scopes are the control, not a prompt.
- Allowlist changes for OAuth need a restart.

## Rejected and deferred

- A second authorization server or a login UI of Sidekick's own: rejected; FastMCP's proxy is used.
- Scopes carried by the client or read from the upstream grant: rejected.
- Distinguishing credential kinds by prefix or by scope naming alone: rejected in favour of the `purpose` column.

## Evidence

- `backend/src/sidekick/shared/auth/service.py`
- `backend/src/sidekick/admin/cli.py`
- `backend/src/sidekick/shared/types/core.py`
- `backend/src/sidekick/mcp/auth.py`
- `backend/src/sidekick/mcp/oauth.py`
- `backend/src/sidekick/companion/service.py`
- `backend/src/sidekick/companion/operations.py`
- `backend/tests/contract/test_mcp_tool_scope_gate.py`
- `backend/tests/api/test_companion.py`
