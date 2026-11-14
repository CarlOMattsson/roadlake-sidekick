# Backend layering

How the Python backend under `backend/src/sidekick/` is organized and which way dependencies may
point. The rules that matter are enforced by tests; this page explains them. Executable truth is the
code and `backend/tests/policy/test_interface_layering.py` (see
[ADR-004](../../decisions/adr/ADR-004-documentation-authority-and-sync.md)).

## Layers

```text
  interfaces        api/ (FastAPI)          mcp/ (FastMCP tools and MCP Apps resources)
                       \                        /
  shared records        structured/  (records and `*_structured` reads both interfaces return)
                                |
  application       <domain>/application/   use cases, ports (Protocols), idempotency and audit rules
                                |
  domain            <domain>/domain/        entities, value objects, rules; no framework imports
                                |
  persistence       shared/persistence/     SQLAlchemy rows, owner-filtered stores, transaction boundary
```

- **Domain** (`tasks/domain`, `projects/domain`, `contacts/domain`, `journal/domain`, ...): plain
  Python. No SQLAlchemy, FastAPI or FastMCP, so business rules are testable without a database,
  worker or model.
- **Application** (`<domain>/application`): the use cases, for example `TaskService`. Each service
  declares the persistence operations it needs as a small `Protocol` (such as `TaskStore`) and
  imports neither `sqlalchemy` (`test_package_boundaries.py`, empty debt) nor the persistence package
  (`test_interface_layering.py`, whose exception list `APPLICATION_PERSISTENCE_EXCEPTIONS` is empty
  and may only shrink). Services take an `Actor` (verified user id and scopes),
  check the scope (`actor.require("tasks:read")`), and carry the business flow, so every
  interface gets the same behavior.
- **Persistence** (`<domain>/persistence`, `shared/persistence`): each context has its own store
  (`SqlTaskStore`, `SqlContactStore`, `SqlJournalStore`, `SqlWorkStore`, `ShoppingStore`, ...) in its
  own `persistence` module, built on a `StoreBase` (`shared/persistence/stores`) that holds the
  session factory, the transaction boundary, idempotency and audit. A store inherits only its own
  context's operations; the few reads it borrows from another context (a Task for a Contact link, a
  tag for a record) are delegated to small ports it is given in `create_stores` in
  `composition.py`. Every read and write filters by `owner_id`. Persistence adapters never
  import an application package. The smallest domains (references, search) keep their own
  `persistence.py` next to the service.
- **API** (`api/`): FastAPI routes, mainly the companion routes used by the Android app. They
  parse, authenticate and call application services or `structured` functions.
- **MCP** (`mcp/`): curated tools and the MCP Apps resource. A handler calls the same application
  services as the API and never calls Sidekick's own HTTP API.
- **Transport layers hold no SQL.** Neither `api/` nor `mcp/` imports `sqlalchemy`,
  `sidekick.shared.persistence` or any context's own `persistence` module; they reach data only
  through the `Container`'s services, the companion's device, push-subscription and reminder
  services included. The one database type they need, the session factory of `create_app`'s test
  seam, is re-exported as `sidekick.composition.SessionFactory`, and the readiness probe is the one
  place that hands the container's session factory on. There are no remaining exceptions; a future
  one must be listed with a reason in `TRANSPORT_PERSISTENCE_EXCEPTIONS` in the layering test.
- **Shared records** (`structured/`): the reads and write results both interfaces answer with, so
  neither interface imports the other.

Cross-cutting code (`shared/`) holds configuration, auth, errors, observability and the common
types. `composition.py` is the composition root: `create_container(settings)` builds one
`Container` of services that FastAPI, the MCP entrances and the workers all share. It imports
neither interface layer.

## Import rules that are tested

`backend/tests/policy/test_interface_layering.py` reads imports from the source and fails when:

- a module in `mcp/` imports `api`, or an `api/companion*.py` module imports `mcp` at runtime (the shared code
  lives in `structured/`);
- a module outside `api/` imports `api`, even for types; `api/app.py` importing `mcp` to mount it is the one
  deliberate meeting point and is not a rule breach;
- a module in `api/` or `mcp/` imports `sqlalchemy` or `sidekick.shared.persistence`;
- `structured/` or `composition.py` imports either interface (`api` or `mcp`);
- a persistence adapter or a domain package imports an `application` package;
- an `application` module outside `APPLICATION_PERSISTENCE_EXCEPTIONS` imports
  `sidekick.shared.persistence`.

`backend/tests/policy/test_package_boundaries.py` covers the rest of the dependency rules (domain,
application, shared kernel, cross-readers, no `sqlalchemy` in service modules). Its `DEBT` list holds
the known violations and only shrinks.

## TxSession

`TxSession` (in `shared/types/tx.py`) is the type of the open unit of work. Most application services
never open a session. They call `store.transaction(operation)`; the store opens a transaction
(`session_factory.begin()`, with a telemetry span), passes the session to `operation`, and commits
or rolls back when it returns. The store methods the operation calls take the session as their first
argument and keep the owner filter inside. Naming the type in `shared/types` lets the application
layer's ports be typed without importing the persistence package.

The Memory services are the one exception to the callback form: their port offers the context managers
`store.read()` (a read-only session, rolled back when the block ends) and `store.begin()` (a transaction that
commits when the block ends without an error), and the service holds the session inside the block.

Runtime processes never run DDL. Schema changes are migrations, applied by the explicit migrator
role before the new image starts (`docs/start/self-hosted-server.md`, `migrations/`).

## ToolContext

Every MCP tool module in `mcp/` exposes one public registrar, `register_<area>_tools(mcp, ctx)`, and
`server.py` builds a single `ToolContext` (`mcp/tool_context.py`) and passes it to all of them. A
module registers its individual tools with small functions of the form `_register_<tool>(mcp, ctx)`.
`ToolContext` is the frozen dataclass they receive:

| Field | Purpose |
| --- | --- |
| `container` | The shared `Container` of application services and settings. |
| `actor_provider` | Returns the verified `Actor` of the current request; scopes are checked server-side. |
| `instrument` | The span and log wrapper that every tool uses (`@ctx.instrument("tool_name")`). |

Tool bodies stay thin: take the actor, call a service or a `*_structured` function, shape the
curated output. The tool annotations (`READ`, `WRITE`, `DESTRUCTIVE`) live once in `mcp/annotations.py`
and the closed-record base `Output` once in `structured/base.py`; modules import them. Tool names,
schemas and annotations are public contracts, described in
[MCP Apps](mcp-apps.md) and generated into `contracts/`.

## Workers and operator commands

Background workers (automation, memory, push, backup) and the operator CLIs are entrances beside the
two interfaces, not a product surface of their own. The automation worker builds the shared
`Container`; the memory, push and backup workers create their session factory from the same
settings and use the store directly, under the same least-privilege runtime role.
