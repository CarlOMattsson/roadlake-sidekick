# ADR-009: One curated public MCP surface, rendered in Claude, with the companion API for Android

- Status: Accepted (D-092, 2026-11-11); records the delivered design and supersedes ADR-001 and ADR-002, no behaviour changed
- Date: 2026-11-11
- Owners: Sidekick application maintainers

## Context

ADR-001 and ADR-002 were written in August 2026, when Sidekick had three model-facing surfaces (a public MCP
server, a run-scoped agent server and an in-process Chat gateway), a React web application and 47 public tools.
Since then the old web shell was removed (D-082) and so was the chat runtime with everything that served only it
(D-084). Both ADRs carried dated "Current state" notes, but their bodies still
describe surfaces that no longer exist. ADR-004 requires that a decision which replaces another is marked as
superseded; this ADR records what those two ADRs now stand for, so that a reader has one current statement.

## Decision

### Sidekick is MCP-first with one public, curated server

The assistant is Claude, reached through the public MCP server mounted at `/mcp` (`MCP_MOUNT_PATH` in
`backend/src/sidekick/mcp/__init__.py`, mounted in `backend/src/sidekick/api/app.py`). It is Streamable HTTP, signed in
through FastMCP's OAuth proxy in front of GitHub or with a hashed personal access token (ADR-007), and a local client
may start `python -m sidekick.mcp.stdio` instead. The size of the contract is not fixed in prose: the committed
`contracts/mcp-tools.generated.json` is the list (95 tools on 2026-11-11), exported by
`backend/src/sidekick/mcp/export_contract.py` and held by `backend/tests/contract/test_generated_contracts.py`.

The principles of ADR-002 stand unchanged. The contract is closed and reviewed; every tool has bounded schemas,
explicit annotations and server-side scope checks; FastMCP handlers and every other entrance call the same use
cases and never Sidekick's own HTTP API; raw table access and model-supplied authorization are rejected. Writes are
direct, permission-checked, idempotent commands (ADR-006); the journal draft is the one place where AI-derived text
is reviewed before it becomes a record.

### The interface is MCP apps rendered inside Claude

Sidekick ships no standalone web application and no desktop shell. Its screens are one MCP app resource
(`ui://sidekick/app-v1.html`, `backend/src/sidekick/mcp/sidekick_app.py`) built from the React rooms in `frontend/`
(`frontend/vite.mcp-app.config.ts`) and shown by the Claude host next to the conversation. The rooms that a server
offers are chosen with `SIDEKICK_ENABLED_ROOMS`.

### There is no built-in chat or conversation runtime

Sidekick runs no conversation, no model call for chat and no run-scoped agent. The agent server (`/agent-mcp/`), the
read-only agent profile with its 14 reads, the in-process Chat gateway and the proposal/confirmation flow are gone
(D-064, D-082, D-084). Claude holds the conversation and calls the tools above. The model-using parts that remain
are the optional memory layer, which sits behind a port (ADR-008), and the automation worker.

### The companion API serves the Android app

The Android app (ADR-005) is the second surface. It does not speak MCP; it uses a separate adapter under
`/companion/v1` (`COMPANION_PREFIX` in `backend/src/sidekick/api/companion.py`) over the same use cases, authenticated
with a purpose-separated device credential (ADR-007). It is off unless `SIDEKICK_COMPANION_ENABLED` is set, and then
it is the only HTTP API that remains beside `/mcp`.

## Consequences

- There is exactly one public model-facing contract, and its size is read from the generated file, not from text.
- Adding an entrance for another client means a thin adapter over the use cases, as the companion API is.
- ADR-001's rule that credentials and surfaces are separated by trust boundary still holds for what remains
  (public token versus device credential), but it no longer has a loopback agent surface to protect.

## Rejected and deferred

- A built-in chat runtime or a model-driven agent inside Sidekick is rejected (D-084).
- A standalone web client is rejected (D-082); a later iPhone app is deferred (ADR-005).

## Supersession

- ADR-001 is superseded (now in `history/`): surfaces 2 (agent server) and 3 (Chat gateway) and the "47 tools" figure no longer
  apply. Its stdio entrance, token handling and neutral manifest remain in force.
- ADR-002 is superseded (now in `history/`): the agent profile, the Chat gateway, the React application as a consumer and the
  "47 tools" figure no longer apply. Its curated-contract and shared-use-case rules remain in force.

## Evidence

- `backend/src/sidekick/api/app.py`, `backend/src/sidekick/mcp/__init__.py`, `backend/src/sidekick/mcp/server.py`
- `contracts/mcp-tools.generated.json` and `backend/tests/contract/test_generated_contracts.py`
- `backend/src/sidekick/mcp/sidekick_app.py`
- `backend/src/sidekick/api/companion.py`
- `docs/decisions/log.md` (D-064, D-082, D-084)
