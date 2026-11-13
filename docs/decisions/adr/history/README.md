# Historical ADRs

Records kept for their reasoning only. Each one is superseded, and nothing in it describes the
current system. The active ADRs stay one level up, in [`../`](../).

| ADR | Status |
| --- | --- |
| [ADR-001: Separate local MCP surfaces by trust boundary](ADR-001-local-mcp-surfaces.md) | Superseded by ADR-009 (2026-11-11). Two of its three surfaces and the web API were removed; ADR-009 restates what still holds (credentials and surfaces separated by trust boundary). |
| [ADR-002: Keep MCP as a curated contract over shared use cases](ADR-002-curated-mcp-contract.md) | Superseded by ADR-009 (2026-11-11). The agent profile and chat gateway were removed; the curated-contract and shared-use-case rules live on in ADR-009. |
| [ADR-003: Isolate the persistent browser QA environment](ADR-003-ai-owned-local-qa-lifecycle.md) | Superseded by D-082 (2026-11-10). The browser interface it governed was removed; the isolation principle lives on in the disposable per-run test databases (`tools/test-db-pool.md`). |
