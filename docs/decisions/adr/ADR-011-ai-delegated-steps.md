# ADR-011: AI-delegated steps: the owner approves a plan, Claude Code runs the steps, the owner accepts the result

- Status: Accepted (D-096, 2026-11-16); amends ADR-009 (the rejection of a model-driven agent inside Sidekick)
- Date: 2026-11-16
- Owners: Sidekick application maintainers

## Context

ADR-009 and D-084 removed the built-in chat runtime and rejected "a model-driven agent inside Sidekick". The owner
now wants to mark a task as possible to do with AI, have Claude plan it in conversation, approve that plan, and
have the steps marked for AI carried out without doing them by hand. Two things must hold: AI-derived writes stay
proposals until a person commits them (D-009), and Sidekick does not become a chat engine or a model gateway again.

The decision splits the work in two stages. Stage 1 (this ADR, delivered first) lets the owner's own Claude Code
run the steps over the public MCP server. Stage 2, already decided by the owner (D-096) and written up as its own
ADR when it is built (D-097), adds an optional runner on the server that calls a model with the owner's API key.
Nothing in stage 1 depends on stage 2.

## Decision

### A task is marked, a plan is a set of steps, and a run is a row

- `tasks.ai_possible_since` marks a task as possible with AI, like `ambition_since`. The mark costs nothing and
  `update_task` sets or clears it with `changes.ai_possible`.
- The plan is the task's own steps. Each step has a `performer` (`owner` or `ai`); an AI step also carries a
  validated `ai_spec` (`AiStepSpecV1`). There is no separate plan table.
- Every attempt at an AI step is one row in `ai_step_runs`, with its state, result, question, review comment, token
  counts and cost. The table is append-only for the application role (no DELETE grant), like the webhook tokens.

### The owner commits the plan; the commit is bound to the plan's content

- Claude writes the plan with `set_ai_plan`, a structured proposal. It never approves it.
- `approve_ai_plan` is app-only (`visibility=["app"]`), carries `anthropic/requiresUserInteraction`, needs
  `tasks:write` and takes the plan's current digest. Four independent gates, so a model that calls tools cannot
  commit its own plan.
- The approval stores a SHA-256 digest over the canonical JSON of the task's title and description and every active
  step (id, title, performer, instruction, `ai_spec`, action titles). Every start recomputes the digest and refuses to
  run when it differs, so a plan changed after approval, by any client, is not run. No trigger or invalidation
  step is needed in the write paths.

### AI steps produce text inside Sidekick and nothing else

- A spec's `effects` is `none` or `draft`. Sending, buying, deleting and publishing are never AI steps; they are
  owner steps, and the server validates that. Fixed stop conditions (sign-in, payment, personal data in a form,
  anything that sends, buys, deletes or publishes, doubt about the goal or the budget) are added to every brief and
  cannot be removed.
- The brief a run receives is rendered from the validated spec as Markdown with front matter. The task text it
  carries is fenced and labelled as data, not instructions, and zero-width and bidirectional control characters are
  removed. The brief uses the same closed field set as memory documents and never contact e-mail, phone or address.
- A result always lands as "to review". Only the owner accepts it (`review_ai_step_result`, which the model may
  call at the owner's spoken request because accepting is undone with an ordinary write); accepting is the only
  thing that completes the step.

### A new opt-in scope, `ai:run`

`ai:run` allows `start_ai_step` and `report_ai_step_result`. It is opt-in like `automation:*`: a default token never
has it, and it is not part of the OAuth session ceiling unless the operator adds it. The recommended token for a
Claude Code run holds `ai:run` and `tasks:read` but not `tasks:write`, so that client cannot approve a plan, accept
a result or move anything to the trash. `automation:*` keeps its meaning and is not reused. ADR-007 lists the scope.

### The owner's Claude Code is the runner in stage 1

Sidekick never starts Claude Code, never receives a claude.ai sign-in and never runs with one. The owner runs their
own client, for example `claude -p "/mcp__sidekick__ai_steps <step>"` or an interactive session, which uses the MCP
prompt `ai_steps`. Cost reported by the client is a client-side estimate and is stored with its source; it does not
count against the money cap. The guards are counters: three attempts per step and 50 starts per day (settings).

### Caps and the local-model exemption

Defaults: 2 USD per task, 50 USD per month, three attempts per step, 50 Claude Code starts per day. A cost source of
`none` (a local model) can be exempted from the money cap by a setting; the rule exists in the domain in stage 1 and
is used by the server runner in stage 2.

### The server runner is decided and will have its own ADR

The owner has also decided (D-096) that Sidekick may later run approved steps on the server through a separate worker
that calls a provider with the owner's API key: a separate process, network, secret and queue, no chat engine, no
sampling. It is recorded in ADR-012 / D-097 when it is built. D-084's removal of the provider adapters is not
reversed: no chat engine is reintroduced, only a narrow loop that returns one structured result.

## Alternatives rejected

- Fields only, with spec and result on the step: loses per-attempt history, cost and leases.
- A separate plan table: duplicates the steps and creates a synchronisation fault.
- Free text as the only instruction: tool list, budget and effects could only be advice, not enforced.
- Invalidating the approval in every write path: many places to forget; recomputing the digest at start is one.
- Reusing `automation:*`: reserved for process runs with a different meaning.
- MCP sampling as the runner: being phased out and not supported by Claude.ai.
- Heuristic prompt-injection filters: unreliable; the controls are the missing channel and the missing effects.

## Consequences

- A tool that calls other tools cannot approve a plan or complete a step by itself.
- A plan edited after approval silently becomes unrunnable until it is approved again; the read model shows
  `changed_since_approval`.
- The brief, the digest and the effect rules are one domain module that both run paths share.
- Telemetry carries counters only; prompts, results and answers are never logged.

## Evidence

- `backend/src/sidekick/work/domain/ai_spec.py`
- `backend/src/sidekick/work/domain/ai_plan.py`
- `backend/src/sidekick/work/domain/ai_runs.py`
- `backend/src/sidekick/work/application/ai_plans.py`
- `backend/src/sidekick/work/application/ai_runs_service.py`
- `backend/src/sidekick/mcp/ai_step_tools.py`
- `backend/src/sidekick/mcp/tool_scopes.py`
- `backend/src/sidekick/shared/auth/service.py`
- `migrations/112_ai_steps.py`
- `contracts/mcp-tools.generated.json`
- `docs/reference/scopes.md`
- `docs/operate/ai-steps.md`
- `backend/tests/unit/test_ai_steps_domain.py`
- `backend/tests/mcp/test_ai_step_tools.py`
