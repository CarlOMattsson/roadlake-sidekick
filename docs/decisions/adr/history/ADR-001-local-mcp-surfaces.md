# ADR-001: Separate local MCP surfaces by trust boundary

- Status: Superseded by ADR-009 (surfaces 2 and 3 were removed by D-084 and the HTTP API by D-082). ADR-009 restates what still holds; this record is kept for its reasoning only.
- Date: 2026-08-23
- Owners: Sidekick application maintainers

## Context

> Note (2026-11-11): the Journal agent job and the Ordinary Chat engine described in this Context no longer exist
> (D-084). Only the public curated MCP server remains; the text below is the original background.

Sidekick has more than one model-facing tool boundary. A personal client needs a stable,
owner-authorized interface, while a live Journal agent job needs a smaller, run-scoped read
surface. Ordinary Chat also needs actor-bound reads without creating another network service.
Treating these as one endpoint would blur credentials, scopes, lifecycle, and failure behavior.

## Decision

> Current state (2026-11-10): only surface 1 exists. The agent server (2) and the Chat gateway (3) belonged
> to the chat engine and were removed by D-084. The number of public tools is not fixed here: the committed
> `contracts/mcp-tools.generated.json` is the list (95 tools on 2026-11-10). The text below is kept as the
> original decision.

Sidekick keeps three explicit surfaces:

1. The public curated MCP server is Streamable HTTP at `/mcp/`, authenticated on every request
   with a hashed, revocable personal access token. It exposes the curated public contract (47 tools when this was written).
2. The agent server is Streamable HTTP at `/agent-mcp/`, but is loopback-only, requires both a
   live job identifier and its job credential, and exposes exactly the 14 read tools of the
   `sidekick-readonly` profile. It is not a general client endpoint and is not published through
   central ingress.
3. Ordinary Chat uses an actor-bound in-process gateway. It has no MCP URL and is not changed by
   additions to the public contract.

Local clients reach the surfaces through the running backend (`/mcp/`), or through
`python -m sidekick.mcp.stdio` for a client that starts a local process. A secret-free,
client-neutral manifest of the public tools is produced by `python -m sidekick.mcp.export_contract`
(committed as `contracts/mcp-tools.generated.json`). A token is supplied through the client's own
configuration or environment, never in command arguments or repository configuration.

## Consequences

- Public clients get a stable, reusable MCP endpoint with explicit owner scopes.
- Agent credentials cannot be reused as general personal tokens, and the agent surface cannot be
  reached through the public proxy.
- There is no universal client configuration file: MCP clients differ in their secret stores and
  configuration formats, so Sidekick emits a neutral manifest and documents adaptation.
- A health check can verify the real public handshake and contract rather than treating an HTTP 401
  or 405 mount response as a successful MCP exchange.

## Rejected and deferred

- A local unauthenticated bypass of the HTTP endpoint is rejected. The stdio entrance is the one deliberate
  exception: the process is started by the local operating-system user and acts as one configured owner
  (`SIDEKICK_MCP_STDIO_OWNER_ID`), without a token; its trust model is in `backend/src/sidekick/mcp/stdio.py`.
- A single endpoint with a mode query parameter is rejected.
- OAuth protected-resource discovery for the private PAT deployment is deferred until the external
  authentication boundary is deliberately expanded.

## Evidence

- `backend/src/sidekick/api/app.py` mounts `/mcp` (it no longer mounts `/agent-mcp`).
- `backend/src/sidekick/mcp/server.py` defines the public curated server.
- The loopback-only agent transport and the 14-read profile
  were part of the chat engine and were removed by D-084 (`docs/decisions/log.md`).
- `backend/tests/mcp/test_transport.py` verifies authenticated Streamable HTTP discovery.
- `backend/src/sidekick/mcp/stdio.py` serves the local stdio entrance and `backend/src/sidekick/mcp/export_contract.py` exports the tool contract.
