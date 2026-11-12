# ADR-002: Keep MCP as a curated contract over shared use cases

- Status: Accepted; Superseded in part by ADR-009 (the agent profile and the Chat gateway were removed by D-084, and the proposal flow by D-064; see the note under Decision)
- Date: 2026-08-23
- Owners: Sidekick application maintainers

## Context

Sidekick is MCP-first, but MCP must not become a raw database adapter or a second business-rule
implementation. Public clients, the React application, and Chat need the same authorization,
validation, idempotency, ownership, and safe-error behavior.

## Decision

> Current state (2026-11-10): the size of the contract is whatever `contracts/mcp-tools.generated.json` lists
> (95 tools on 2026-11-10), and the agent profile and Chat gateway named below no longer exist. Writes are now
> direct, permission-checked commands; the journal draft is the one place where AI-derived text is reviewed
> before it becomes a record (D-009). The text below is kept as the original decision.

The public FastMCP server remains a closed, reviewed contract (47 tools when this was written). Every tool has a stable
name, bounded input and output schemas, explicit annotations, server-side scope checks, and a
structured result. FastAPI routes and FastMCP handlers call the same application use cases; MCP
handlers never call Sidekick's own HTTP API.

Writes remain explicit, idempotent application commands. As originally decided, AI-derived writes were
validated proposals with a review/commit boundary, not direct MCP execution by a model (now only the journal
draft, see the note above). The generated contract at
`contracts/mcp-tools.generated.json`, the discovery tests, and the application code are authoritative.

The run-scoped agent surface derives schemas from the curated server where possible, then restricts
them to the 14 declared reads. It is a profile boundary, not a second public catalogue.

## Consequences

- Adding a public tool requires contract, authorization, use-case, telemetry, and test work.
- Public discovery stays predictable for clients and avoids capability inflation through reflection
  or generic repositories.
- The generated contract is a snapshot of the current surface, while compatibility tests hold the
  reviewed identities and schemas.
- The public list may grow, but the Chat gateway and agent profile do not inherit additions silently.

## Rejected and deferred

- Raw table CRUD, generic tool factories, and model-supplied authorization are rejected.
- A public tool for conversation proposal approval was deferred; the question is moot since D-064
  removed the proposal flow from MCP.

## Evidence

- `backend/src/sidekick/mcp/server.py`
- The chat gateway and the agent transport were removed by D-084 (`docs/decisions/log.md`).
- `contracts/mcp-tools.generated.json`
- `backend/tests/contract/test_generated_contracts.py`
- `backend/tests/mcp/test_transport.py`
