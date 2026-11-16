# ADR-012: The server runs approved AI steps with the owner's own API key

- Status: Accepted (D-097, 2026-11-16); amends ADR-011 (stage 2) and ADR-009
- Date: 2026-11-16
- Owners: Sidekick application maintainers

## Context

ADR-011 lets the owner's own Claude Code run the AI steps of an approved plan. The owner has also decided (D-096) that
Sidekick may run an approved step itself, when the owner presses "Run", with the owner's own Anthropic API key. That adds
a secret that spends money, an outbound channel that carries the owner's data, and model output built on that data. It
must not bring back a built-in chat runtime, a provider registry or an agent (D-084, ADR-009).

## Decision

### A separate worker, network and secret

- `sidekick-ai-worker` is its own process and Compose service (`ai-worker`, profile `ai`), on the internal `data` network
  and a network of its own, `ai`, which is its only route out. It is not on `edge`, where Hindsight and ntfy live.
- The key is `SIDEKICK_AI_ANTHROPIC_API_KEY`, given as a file (`_FILE`) to that service only. The API and the other
  workers refuse to start in production when they see it. Without the key the worker does not start. The key is never
  stored, logged, traced or returned.
- The adapter passes the key and `https://api.anthropic.com` explicitly, retries nothing by itself and has the SDK's
  OpenTelemetry instrumentation off, so no prompt, response or trace header leaves through it.
- Web tools are not built; a step that needs them is refused with `ai_runner_off`. If they are built later they are
  decided in a record of their own.
- A local model is DEFERRED. A step whose privacy is `local_only` is refused with `ai_runner_off` until an adapter for a
  local model exists behind the same port.

### The run row is the queue

- "Run" (`run_ai_plan`) is app-only, carries `anthropic/requiresUserInteraction`, needs `tasks:write` and the plan's
  current digest, and queues the one ready step as an `ai_step_runs` row with `runner = server` and `state = queued`.
- The worker finds the oldest queued row without locking it, locks the run's Task, reads the run again and claims it
  only if it is still queued (the lock order every writer of a run keeps: Task, then run). It holds a lease and returns
  stalled rows. A queued row that is never claimed expires after 30 minutes and does not use an attempt. No
  Procrastinate: one row per run already holds the state, the lease and the history.
- Before every model call, in one transaction, the worker locks the Task, recomputes the plan's digest and compares it
  with the digest the run was queued under and the approved one. A plan changed after approval is not run.

### Attempts count per cycle

- Attempts are counted per cycle of a recurring task, that is, since `tasks.last_completed_at`, and only runs that
  started count. A queued run that was never taken uses no attempt.
- The task cap of 2 USD applies per cycle in the same way. The monthly cap applies per calendar month in the owner's
  time zone.
- This does not change ADR-011's decision. It makes its attempt limit precise and corrects a fault in stage 1, where
  attempts were counted over all cycles, so a recurring task ran out of attempts after three runs in total.

### Money: reserve before, settle after

- Before every call the worker reserves an upper bound of its cost (the request's UTF-8 bytes plus a fixed overhead as
  input tokens, `max_tokens` as output, priced from a dated price table), under a per-owner advisory lock that also
  sees every other reservation. The call is refused when the step's budget, the task's cap (per cycle) or the monthly
  cap would be passed. After the call the reservation is replaced by the cost computed from the response's usage,
  rounded up. A call whose outcome is unknown, or a worker that dies during a call, books the reservation as spent.
- Spent is the sum of cost and outstanding reservations of the run rows whose cost source counts. A client estimate
  never counts; a local model (`none`) counts unless the owner exempts it. A run erased with its Step or Task still
  counts: a trigger keeps its cost, runner and creation time (numbers only, never text) in `ai_erased_run_costs`.

### One structured answer, no tools that act

- The request is the fixed system rules plus the brief rendered by the same domain module as stage 1, with the same
  closed field set; the owner's text is fenced as data. The model has no client tools and there are no web tools.
- The answer is JSON in a fixed schema (`output_config.format`): a result, a question or a failure. The server sets the
  result's format, checks its length and checklist and stores it as "to review". Only the owner's acceptance completes
  a step. Nothing goes to memory.

## Alternatives rejected

- The automation worker as runner: it has no secret and no internet route by design, on every installation.
- Procrastinate for the `ai` family: a second state machine beside the run row, a schema and a dependency to upgrade.
- A spend ledger table: a second truth beside the run rows.
- Agent SDK or `claude -p` on the server; MCP sampling: as in ADR-011.
- A tool loop with a "submit" tool as the answer channel: JSON output is one call and needs no client tool.
- Heuristic prompt-injection filters.

## Consequences

- The caps hold under any number of workers, because every call is reserved under one lock before it is made and no
  call uses a server-side tool. Web tools are taken up in a record of their own when they are built.
- Sidekick's cost figures are estimates that err high; the provider's invoice is the record.
- Customers who do not enable the `ai` profile run no new process and hold no new secret.
- A local model, Bedrock or Vertex is one more adapter behind the same port, recorded when built.

## Evidence

- `backend/src/sidekick/work/domain/ai_cost.py`, `ai_outcome.py`, `ai_model_port.py`, `ai_server_brief.py`,
  `ai_runs.py`, `ai_plan.py`
- `backend/src/sidekick/work/application/ai_server_runs.py`, `ai_runner.py`, `ai_run_support.py`
- `backend/src/sidekick/work/infrastructure/anthropic_model.py`, `backend/src/sidekick/work/ai_worker.py`
- `backend/src/sidekick/shared/config/ai_runner.py`
- `migrations/113_ai_server_queue.py`, `migrations/114_ai_erased_run_costs.py`
- `deploy/selfhost/compose.yaml`, `deploy/selfhost/update.sh`
- `docs/operate/ai-steps.md`
- `backend/tests/integration/test_ai_server_runs.py`, `test_ai_runner.py`, `test_ai_runner_spend.py`
- `backend/tests/unit/test_ai_cost.py`
