# Decisions and architecture records

This folder holds the decisions that Sidekick's code, tests and documents refer to. There are two kinds. The
[decision log](log.md) is a short, numbered list of the product and architecture decisions that hold today. The
[architecture decision records](#architecture-decision-records) (ADRs) record durable cross-cutting decisions and cite
their evidence as files in this repository. Replaced log entries are in the [archive](archive.md).

## Reading `D-NNN` and `ADR-NNN`

| Label | Meaning |
| --- | --- |
| `D-NNN` | A numbered entry in the [decision log](log.md). Code comments, tests and documents cite it, for example `D-083`. The number is stable and never reused. |
| `ADR-NNN` | A numbered architecture decision record in [`adr/`](adr/). Every ADR is also entered in the log under its own `D-NNN`. |
| Accepted | The decision is in force. |
| Delivered | The decision has been built. |
| Superseded | A later decision replaced it. The entry names which one and lives in the [archive](archive.md). |
| Amended | The decision is still in force but changed in part. |

When a log entry and the code disagree, the code and the generated contracts win; the log is a summary. The rules for
which source wins are in [ADR-004](adr/ADR-004-documentation-authority-and-sync.md).

## Architecture decision records

The records are the files in [`adr/`](adr/); the [index](#adr-index) below lists them with their status.

## ADR status words

| Status | Meaning |
| --- | --- |
| Accepted | The decision holds. It may be revised to describe the delivered state, with a dated note, as long as the decision itself is unchanged. |
| Superseded in part by ADR-NNN | Some of the decision still holds and some does not. The status line and any "Current state" note say which, and the replacing ADR states what now applies. |
| Superseded by ADR-NNN or D-NNN | Nothing in it describes the current system. It moves to [`history/`](adr/history/README.md) and is kept for its reasoning only. |

## ADR index

| ADR | Status | Subject |
| --- | --- | --- |
| [ADR-001](adr/history/ADR-001-local-mcp-surfaces.md) | Superseded by ADR-009 | Separate MCP surfaces by trust boundary (in `history/`) |
| [ADR-002](adr/history/ADR-002-curated-mcp-contract.md) | Superseded by ADR-009 | A curated MCP contract over shared use cases (in `history/`) |
| [ADR-003](adr/history/ADR-003-ai-owned-local-qa-lifecycle.md) | Superseded by D-082 | Persistent browser QA environment (in `history/`) |
| [ADR-004](adr/ADR-004-documentation-authority-and-sync.md) | Accepted | Executable truth versus explanatory documentation |
| [ADR-005](adr/ADR-005-native-android-app.md) | Accepted | Official Android app |
| [ADR-006](adr/ADR-006-persistence-and-idempotent-writes.md) | Accepted | PostgreSQL roles and idempotent writes |
| [ADR-007](adr/ADR-007-authentication-credentials-and-scopes.md) | Accepted | Credentials and scopes |
| [ADR-008](adr/ADR-008-derived-memory-with-hindsight.md) | Accepted | Derived, optional memory |
| [ADR-009](adr/ADR-009-one-curated-public-mcp-surface.md) | Accepted | The current MCP-first architecture |
| [ADR-010](adr/ADR-010-one-error-tree.md) | Accepted | One error tree rooted at SidekickError |

## Numbering

Numbers are never reused. ADR-001 to ADR-003 are not missing: they are superseded and live in `history/`, so the active ADRs in this
folder start at 004. A new ADR takes the next free number.
