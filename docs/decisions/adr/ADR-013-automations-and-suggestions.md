# ADR-013: Automations propose, the owner decides, and an independent check gates only convenience

- Status: Accepted (D-098, 2026-11-22); amends ADR-009, ADR-011 and ADR-012 (stage C only) and gives the scopes `automation:read` and
  `automation:write` their first meaning in ADR-007. Partly amends D-064, for suggestions only.
- Date: 2026-11-22
- Owners: Sidekick application maintainers

## Context

The owner wants recurring AI work over untrusted input such as mail, and wants what it finds as drafted changes that can be approved
quickly. Three things must hold. Prompt injection must not be able to cause an action. The cost must stay inside the caps that exist
(ADR-012). Sidekick must not turn back into a conversation engine or an agent platform (D-084, ADR-009). It also has to work without a Claude
subscription and without OpenRouter.

ADR-011 and ADR-012 already give a money-safe, secret-isolated model path for owner-approved steps. This ADR reuses its hard parts (the
model port and adapter, the price table, the reservation under one lock, the worker loop, the fencing of the owner's text) and does not
reuse its Task-bound plan code.

## Decision

### The registry: an automation is its own aggregate

- An automation is an owner-scoped record with its own tables. It is never a Task, so no everyday view, search, push reminder or memory
  document can show it. Making it a Task was considered and rejected (below).
- It holds a title, a one-sentence purpose, the owner's instruction (trusted, becomes the brief), a closed set of sources, a runner
  (`claude`, `claude_code`, `server`, `any`), a cadence, the allowed effects, the apply mode and the thresholds, a per-run budget and a
  `model_tier`.
- The spec is bound to a SHA-256 digest. The owner approves it in the app (`approve_automation`, app-only,
  `requiresUserInteraction`). A changed spec is not runnable until it is approved again; the read model shows
  `changed_since_approval`. A model can edit only a draft (`save_automation`), never approve it.
- An automation is archived, never erased, so its run costs stay counted.
- Automations are enabled per installation by default and are part of every licence tier. The default `apply_mode` is `suggest` per
  automation.

### Model tiers

- `model_tier` is `standard` (default) or `strong` and is part of the spec digest. `standard` runs on a very cheap model through the
  OpenAI-compatible adapter (for example a flash-class model via OpenRouter); the model id is a setting and is never hard-coded.
  `strong` runs on the configured Anthropic model (ADR-012).
- The tier is visible in the registry read model and in the report. If the `standard` provider is not configured, a `standard`
  automation refuses to run with a clear reason. It never falls back to `strong`.
- A key sent to a private model server over plain `http` is the operator's own choice. The operator docs say so; it is not forbidden.

### Runs

- A run is one row per attempt at one occurrence, unique on `(automation, occurrence key, attempt)`. The occurrence key is the
  scheduled day in the owner's time zone, or a fresh id for "run now". There is at most one active run per occurrence, so starting a
  routine twice returns the same run.
- A run is claimed by Claude or Claude Code (scope `automation:run`) or queued for `sidekick-ai-worker` (`runner = server`). The run
  row is the queue, as in ADR-012. The spec digest is recomputed before every model call.
- Attempts per occurrence: three. Run rows are append-only.

### Output: datapoints and suggestions from a closed catalogue

- A run writes **datapoints** (facts of a closed kind, with validated fields and a source fingerprint that is a keyed digest, never the
  raw reference) and **suggestions**.
- The effect catalogue is closed and versioned: `create_task.v1` and `create_contact.v1`. Their payload schemas reuse the bounds of the
  existing create inputs and can be extended only by a new version, never reshaped. Suggest-only effects (`add_shopping_items`,
  `link_contact_to_task`, `add_contact_detail`) are DEFERRED. Send, delete, trash, complete, archive, pay, buy and publish are not
  representable.
- Text written by the AI (summary, rationale, source labels) is untrusted: it is stored with bounds, shown escaped and labelled
  "written by AI".
- A dismissed suggestion is never proposed again: the dedupe fingerprint is unique across all states. Pending suggestions expire after
  14 days.

### Deterministic screening: always on, before any model check

- At write, a suggestion is refused (with a code per index) when its schema is invalid, its effect is not allowed, it is over the
  bounds or the per-run cap, it refers to a record that is not the owner's or is trashed, or the run is not running.
- Text is normalised (NFC, control, zero-width and bidi characters stripped) and Markdown images and HTML are rendered inert.
- A closed, versioned list of flags keeps the card but marks it, and a flagged card is never in a group, never auto-applied and never
  decidable by a model tool: `contains_link`, `payment_related`, `contact_detail_unverified`, `homoglyph_domain`,
  `instruction_like_text`, `duplicate_existing`, `large_batch`. A new flag is a new code, never a change of meaning. Heuristic filters
  are a signal, not the control.

### The independent check

- Confidence is a whole number from 0 to 100 and comes **only** from the independent checker. A self-rating by the proposer is never
  stored or shown.
- The checker runs in `sidekick-ai-worker` only, the one process that may hold model keys (ADR-012). It is tool-less. It is
  configured with `SIDEKICK_AI_CHECK_*` (provider `off` by default, `anthropic` or `openai_compat`, with a model, a base URL and a key
  file). A checker model different from the proposing model is preferred.
- It sees the automation's title, purpose, sources and allowed effects, and for each suggestion its effect, its normalised payload,
  the kinds of its datapoints and sources, the source labels and the deterministic flags, all fenced as untrusted data. It never sees raw
  input bodies, other suggestions, other records of the owner or the proposer's rationale (the rationale is the most persuasive channel
  for an injection).
- It answers in a fixed schema with codes only (verdict `ok`, `uncertain` or `suspicious`, a confidence, and reason codes from a
  closed set). It has no free text, so there is no injection channel from the checker back to the owner's screen. An unknown id, a
  missing id or malformed output makes the whole check `error`, and every card of that run shows "Not checked".
- The check never authorises anything. It only adds a warning and gates two convenience paths, the group and auto-apply. Without a
  configured checker there is neither a group nor auto-apply; each card is decided alone and shows "Not checked".

### Applying: only the owner's decision or the approved auto policy

A suggestion is applied by one of three routes, always through the domain's in-session use case (`TaskService.create_in_session`, a
public `ContactsService.create_in_session`) in one transaction with the suggestion row locked, its state and version checked and the
payload validated again.

1. **In the app**, one at a time (the owner may edit the payload first; the original is kept and the card shows "edited by you"), or as
   a group of at most 25 per call. The group is shown per automation and is bound to `group_digest`, a SHA-256 over the sorted
   `(id, version)` pairs the owner saw. `approve_suggestion_group` is app-only and `requiresUserInteraction`, recomputes eligibility and the
   digest, and refuses the whole call if either changed. A card is group-eligible only when it was checked, its verdict is `ok`, its
   confidence is at least the automation's bulk threshold (default 90), it has no flags, its effect is low-risk, it is not edited and the
   run is done.
2. **By the model**, with `decide_suggestions`, at most three items per call (`maxItems: 3` in the schema, not only in the
   description). It is refused for a flagged card and with `same_session` for the MCP session that claimed the run. A suspicious card
   needs a second explicit tap in the app. "Approve the group" by voice therefore approves three at a time. This partly amends D-064,
   for suggestions only.
3. **By an opt-in auto policy** per automation. `apply_mode = auto_low_risk` and `auto_effects` are part of the approved digest, so a
   model cannot switch them on. Only `create_task` and `create_contact` qualify, a checker must be configured, the verdict is `ok`
   with a confidence of at least the auto threshold (default 95), there are no flags, a contact's e-mail domain matches the source
   sender's domain, and fewer than 10 have been auto-applied in the run and 25 today. Anything else stays a pending card. Auto-applied
   items are listed first in the inbox and in the report with Undo, and are never silent. The audit attribution is `decided_by = policy`.

Idempotency: the inner call uses the derived key `sugg:{suggestion_id}:v{version}`, so a retry, a second worker or a group call that
overlaps a single call can never create a record twice (ADR-006). The outer tool call keeps the client's key.

Undo moves the created record to the trash (D-062) and is allowed only while the record still has the version it was created with and is
not trashed. Otherwise the server refuses with `changed_since_apply`.

### Scopes

- `automation:read` (list and get automations, runs, suggestions and the report) and `automation:write` (drafts, pause, archive,
  decide and undo suggestions together with the target domain's write scope, mark the report seen) are opt-in and now have their first
  meaning. `automation:run` is new and opt-in: `start_automation_run`, `record_automation_results`, `submit_automation_inputs`, and
  nothing else. It cannot decide, approve or write any domain record.
- A default token holds none of them. The recommended routine token holds `automation:run` only; the recommended owner connector holds
  `automation:read` and `automation:write` without `automation:run`.
- `approve_automation` also requires the approving actor to hold the write scope of every allowed effect, and the auto policy acts with
  exactly the scopes of its `auto_effects`.
- ADR-011 said that `automation:*` keeps its meaning and is not reused for AI steps. That still holds: the AI-step scope stays `ai:run`.
  What changes is that the reserved names are no longer reserved for something else.

### Runners and what the server can guarantee

- **Server pipeline (stage C, profile `ai`):** the isolation is enforced. The worker makes three separate tool-less structured calls
  with fixed schemas. **Extract** sees the submitted raw inputs fenced as data and writes datapoints only. **Propose** sees the
  datapoints, the instruction and the allowed-effect schemas, and never the raw text. **Check** is the independent check. In internal
  mode the worker reads Sidekick data through the same closed field set as memory documents. No call has client tools and no web tools
  are built (ADR-012). Raw inputs (the full fetched source text before it is reduced to datapoints) are purged when the run ends and in
  any case within 24 hours.
- **Claude or Claude Code as runner (stage A):** the model that reads the mail is the client's. Sidekick enforces what it receives: the
  catalogue, the screening, the caps, the dedupe, the check and the owner's decision. It cannot enforce that the client calls no other
  tool. A Claude scheduled task includes all of the owner's connectors by default and runs in auto mode, so a Sidekick connector with
  full scopes in the routine could be steered to call `create_task` directly, outside the suggestions path. The control is a narrow
  credential for routines (`automation:run` only). The refusals `same_session` and the three-per-call limit, and the fact that every
  effect is undoable, narrow the damage. The operator docs state it plainly: with Claude as the runner, the protection is the narrow
  credential.
- Stage A needs no API key at all.

### Money

- Costs are booked on run rows and counted under the existing per-owner advisory lock `ai-spend:{owner}`, with the reservation before
  every call and the settlement after it exactly as in ADR-012. There is no second ledger.
- Defaults: 1.00 USD per run (`run_budget_microusd`, 1 000 000), a sub-cap of 10 USD per month inside the shared 50 USD per month,
  20 runs per day per owner, three attempts per occurrence. Local models (cost source `none`) are exempt through the existing
  setting. A client's own cost figure is stored as `client_estimate` and never counts against the money caps.

### Logging and the report

- Logs, spans and metrics carry ids, closed codes (state, effect, verdict, flag codes, outcome, error category), counts, token counts,
  cost, durations, model names and the runner kind. They never carry instructions, purposes, titles, input bodies, datapoint fields,
  source labels, payloads, rationales, checker output beyond codes, sender addresses, source fingerprints or session ids. A canary test
  asserts this for log records, exported spans, metric labels, audit events and domain events.
- The report is one self-contained HTML file the owner downloads from the app. Everything from the AI is escaped by one renderer. The
  file contains no script and no external resource, has a content security policy of `default-src 'none'; style-src 'unsafe-inline';
img-src data:`, and renders no link from untrusted text. It is a file, not a product surface.

### Tests

Every model output is treated as adversarial. Security tests use obedient fakes: a proposer that does what the injection says and a
checker that answers "ok" with full confidence, and the invariants must still hold. The invariants are: no path outside the catalogue
produces an effect; nothing is applied without the owner's decision or the approved auto policy; flagged cards are never grouped,
auto-applied or model-decided; a changed spec does not run; the caps hold under concurrent workers; logs hold no canary; the report
executes nothing; a runner token cannot decide; a dismissed suggestion does not return. A fixture corpus of known injection patterns
runs in CI against the fakes. A live harness, not part of CI, measures the configured checker's flag and miss rates; its result is a
quality measure and no longer a gate for enabling automations.

## Alternatives rejected

- **An automation as a recurring Task marked automated:** the hidden flag would have to be honoured in the agenda, board, review queue,
  push reminders, today brief, search, memory documents and listing, and each missed place would leak the instruction. It would also
  bend ADR-011's rule that only the owner's acceptance completes a step.
- **Claude only, with no server check:** the check would run in the same client that read the injection, so it is not independent, and
  it would not work without Claude.
- **A spend ledger:** a second truth beside the run rows (ADR-012 rejected one).
- **Heuristic filters as the control:** they are a signal only.
- **Reusing `ai:run`:** that scope starts and reports an approved AI step and means something else.
- **MCP sampling:** as in ADR-011.
- **A model self-rating as confidence:** it is the channel an injection attacks first.

## Consequences

- The effect catalogue and its payload versions, the scope meanings, the confidence semantics (independent checker only, 0 to 100) and
  the occurrence key are hard to change once clients and data exist. They change only by a new version or a new code.
- With Claude as the runner the residual risk is the credential the routine holds. The docs say so and recommend removing other
  write-capable connectors from the routine.
- Customers who do not enable the `ai` profile run no new process and hold no new secret. Stage A needs none. A checker, a `standard`
  provider and the stage C pipeline are opt-in configuration.
- ADR-007 lists `automation:run` with the other opt-in scopes. ADR-009 and ADR-012 gain the stage C calls as a second narrow
  exception to "no model-driven agent inside Sidekick"; D-084 is not reversed and no conversation engine, provider registry or agent returns.
- Web fetch, "check an API" and further effects are DEFERRED and need a record of their own.

## Evidence

Planned. The implementation lands in stages after this record (registry, runs and suggestions, then the checker, then the server
pipeline); the section is completed with the paths when they exist.
