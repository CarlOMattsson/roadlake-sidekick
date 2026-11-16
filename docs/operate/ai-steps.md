# Run AI steps

[Svenska](ai-steps.sv.md)

<!-- description: Let your own Claude Code, or your server with your own Anthropic key, run the AI steps of an approved task, then review what it writes. -->

Some steps of a task can be done by AI: a first draft, research, a summary, a checklist. You approve the plan, your own Claude Code or your own server runs the AI steps, and every result waits for you to review it. An AI step only makes text inside Sidekick. Sending, buying, deleting or publishing is always a step that you do yourself.

## The flow

1. **Mark the task as possible with AI.** Open the ⋯ menu on the task in the Work room, or ask Claude. The mark costs nothing.
2. **Ask Claude to plan the task.** Each step is marked "You" or "AI". Each AI step has a short instruction: the goal, when it is done, the result format, the tools it may use, a budget, and when it must stop and ask you.
3. **Approve the plan in the Work room** with one click. The approval covers exactly this plan. If the plan changes afterwards, nothing runs until you approve it again.
4. **Run the AI steps** with Claude Code, or on your server, as described below.
5. **Review each result** in the room, or ask Claude. You can accept it, ask for another attempt with a comment, reject it, or answer a question the step asked. Only you complete a step.

## Give Claude Code its own token

Claude Code needs a personal token with the scope `ai:run`. That scope is opt-in: no ordinary token has it. Create a token with only what the run needs:

```bash
uv run --project backend sidekick-admin create-token --user-id <USER_UUID> --label "Claude Code" --scope ai:run --scope tasks:read
```

- `<USER_UUID>` is the owner's id, as `create-user` printed it.
- Without `tasks:write` this client cannot approve plans, accept results or move anything to the trash. Add `projects:read` if the answers should name projects, and `contacts:read` if a step needs contacts. The [Scope reference](../reference/scopes.md) lists what each scope allows.
- The token is printed once. Treat it like a password.

> **Warning: never give the model a token with both `ai:run` and `tasks:write`.** Together they let one client run a step, report its own result and then accept it, and approve or edit the plan it runs. That removes the review that keeps you in charge. The local stdio connection carries every scope, so a model reached over stdio has both powers: use stdio only for clients you trust with the whole account, and use this limited token for the client that runs steps.

A personal token works only in the developer mode `pat`. On a server that signs in through GitHub, `/mcp` refuses it, as [Connect Claude](connect-claude.md) explains, so this route is not available there.

## Connect Claude Code

Put the server in a file in the folder where you run Claude Code, for example sidekick.mcp.json. The token stays in an environment variable and never goes into the file:

```json
{
  "mcpServers": {
    "sidekick": {
      "type": "http",
      "url": "https://<your-domain>/mcp",
      "headers": {
        "Authorization": "Bearer ${SIDEKICK_AI_TOKEN}"
      }
    }
  }
}
```

The server name `sidekick` gives the prefix `mcp__sidekick__` to the tools and the slash command. `url` is the `/mcp` address of your server, as in [Connect Claude](connect-claude.md).

## Run the steps

Interactively, start Claude Code with `claude --mcp-config sidekick.mcp.json` and type the slash command with the id of the task. The argument is optional:

```
/mcp__sidekick__ai_steps <task-id>
```

Headless, from a script or a terminal, there are two variants. Claude Code runs the AI steps of the plan in order; a step is ready only when the steps before it are done.

Plan sign-in (your Claude subscription):

```bash
claude -p "/mcp__sidekick__ai_steps <task-id>" --mcp-config sidekick.mcp.json --allowedTools "mcp__sidekick__start_ai_step,mcp__sidekick__report_ai_step_result,WebSearch,WebFetch" --permission-mode dontAsk --output-format json
```

API key, set in the environment and not on the command line:

```bash
export ANTHROPIC_API_KEY=<your-api-key>
claude -p "/mcp__sidekick__ai_steps <task-id>" --bare --mcp-config sidekick.mcp.json --allowedTools "mcp__sidekick__start_ai_step,mcp__sidekick__report_ai_step_result,WebSearch,WebFetch" --permission-mode dontAsk --output-format json
```

- According to Claude Code's documentation, `--bare` does not read the sign-in of a plan. That is why the second variant needs an API key.
- `--allowedTools` lists what the run may use besides Sidekick's own tools. The two web tools are listed here; leave them out if the steps should not search the web.
- `--max-budget-usd` can be added to try a cap on one run. It is not verified here that the flag works with plan sign-in, so check the output and set a limit with your provider too.

## Limits and costs

| Setting | Default | What it limits |
| --- | --- | --- |
| `SIDEKICK_AI_DEFAULT_TASK_CAP_USD` | 2 | Spending per task, in US dollars |
| `SIDEKICK_AI_MONTHLY_CAP_USD` | 50 | Spending per calendar month |
| `SIDEKICK_AI_MAX_ATTEMPTS_PER_STEP` | 3 | Attempts at one AI step in a cycle of its task; a repeating task gets them back each time it is completed |
| `SIDEKICK_AI_CLAUDE_CODE_STARTS_PER_DAY` | 50 | AI steps your Claude Code may start per day |

These are set like the other settings; see the [Configuration reference](../reference/configuration.md). `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP` takes runs on a local model, which cost nothing, out of the money caps.

The cost that Claude Code reports is an estimate. Sidekick stores it with each run but does not count it against the money caps, because a plan sign-in is not billed per call. The protection there is the number of attempts and starts. The money caps apply to runs on your server, as the section below describes.

## Run AI steps on your server

Instead of Claude Code, your own server can run an approved AI step. You press **Run** in the Work room, and a separate container, `ai-worker`, sends the step to the Anthropic API with your own API key and writes the answer back as a result for you to review. It is off until you turn it on.

**Turn it on.**

1. Put your Anthropic API key in a file and start the `ai` profile, as the [Compose profiles](../reference/selfhost-profiles.md) page and `deploy/selfhost/README.md` describe. Write the key to `secrets/ai_anthropic_api_key` directly, or let `secrets-to-files.sh` move it there.
2. Set `SIDEKICK_AI_RUNNER_ENABLED=true` in `selfhost.env` and start the profile with `docker compose --env-file selfhost.env --profile ai up -d`.

The key reaches `ai-worker` only. It must not stay in `selfhost.env`: in production the API refuses to start when it finds the key there. `ai-worker` is also the only container on the `ai` network, the one outbound route to the internet. See [Limits and secrets](limits-and-secrets.md).

**Model.** The default is `claude-opus-5-5`; change it with `SIDEKICK_AI_MODEL`. Sidekick has built-in prices for `claude-opus-5-5` and `claude-sonnet-5-5`. A model that is not in that table needs all four prices (`SIDEKICK_AI_PRICE_INPUT_USD_PER_MTOK`, `SIDEKICK_AI_PRICE_OUTPUT_USD_PER_MTOK`, `SIDEKICK_AI_PRICE_CACHE_WRITE_USD_PER_MTOK` and `SIDEKICK_AI_PRICE_CACHE_READ_USD_PER_MTOK`), because a cost that cannot be counted cannot be capped. Give all four or none.

**How Run works.**

- Run exists only in the app (the Work room). Claude cannot press it for you, and it needs the permission to change tasks.
- You press Run on an approved plan. The next AI step is queued. `ai-worker` takes it within a few seconds (`SIDEKICK_AI_POLL_SECONDS`) and makes a model call.
- The answer is always something for you to review: a result, a question or a failure. Nothing goes to memory, and nothing is sent, bought, deleted or published.
- One step runs at a time, in the plan's order. You press Run again for the next step. You can cancel a run that is queued or running; a call that is already under way is still billed.
- A step marked to run only with Claude Code cannot be run here.

**The money caps.** The server works out what a call can cost before it makes the call.

- Before every call the worker reserves the most that call can cost. It does so under one lock per owner, so two workers can never reserve past the same cap. After the call the reservation is replaced by the cost that the token counts give.
- A call is refused when it would pass the step's own budget, the task's cap (`SIDEKICK_AI_DEFAULT_TASK_CAP_USD`, counted per cycle for a repeating task) or the month's cap (`SIDEKICK_AI_MONTHLY_CAP_USD`).
- Costs are rounded up. Sidekick's figure can be higher than what you pay: Anthropic's invoice is the record.
- A call whose outcome is not known (a timeout, a broken connection), or a worker that dies during a call, books the reservation as a cost. The caps therefore never count less than was spent.
- A run still counts after you erase its step or task permanently. Sidekick keeps only the run's cost, runner and time (numbers, no text) for as long as your account exists.
- Set a spending limit for the key in the Anthropic Console as an outer guard. Sidekick's caps are the inner one.

**What leaves your machine.** The step's brief goes to Anthropic under Anthropic's API terms. It holds the task's title and description, the step's instruction, the titles of the task's actions, the project's title and, if the step allows it, the names of contacts and the titles of references. Contacts' e-mail, phone and address, journal text and memory are never sent. The key and the brief are not written to the logs or kept in the database; the result, question or failure is kept as the result of the run.

**Not supported yet.** Web search and web fetch are off, and so are local models. A step that needs the web or is marked `local_only` is refused with `ai_runner_off`.

**Settings.**

| Setting | Default | What it does |
| --- | --- | --- |
| `SIDEKICK_AI_RUNNER_ENABLED` | `false` | Turns the server runner on |
| `SIDEKICK_AI_MODEL` | `claude-opus-5-5` | The model that runs the steps |
| `SIDEKICK_AI_SERVER_STARTS_PER_DAY` | 50 | How many steps you may run on the server per day |
| `SIDEKICK_AI_MAX_OUTPUT_TOKENS` | 16000 | The most one call may produce |
| `SIDEKICK_AI_REQUEST_TIMEOUT_SECONDS` | 300 | How long one call may take |
| `SIDEKICK_AI_POLL_SECONDS` | 5 | How often the worker looks for a queued run |
| `SIDEKICK_AI_PRICE_*` | not set | The four prices of a model that is not in the built-in table |

The key itself is `SIDEKICK_AI_ANTHROPIC_API_KEY`, given as the file `ai_anthropic_api_key`. All settings are in the [Configuration reference](../reference/configuration.md).

**If Run does not work.**

| You see | What to do |
| --- | --- |
| `ai_runner_off` | The runner is off, or the step needs the web or a local model. Check `SIDEKICK_AI_RUNNER_ENABLED` on `api` and that the `ai` profile runs. |
| `ai_budget_reached` | The first call would pass the step's budget, the task's cap or the month's cap. Raise the cap, or wait for the next cycle or month. |
| `ai_limit_reached` | The attempts at this step in the cycle are used, or you have run the daily number of steps. |
| The run stays "queued" | `ai-worker` is not running, or Anthropic rejected the key. A run that nobody takes lapses after 30 minutes and uses no attempt. Start the worker or fix the key, then press Run again. |
| A run that was taken and then went silent | It lapses after 15 minutes, and its reservation is booked as a cost. |
| The worker takes no more runs | Anthropic rejected the key, and the worker stops taking runs until it is restarted. Put a new key in the file and restart `ai-worker`. |

## What to know before you run

- Sidekick never starts Claude Code and never receives your Claude sign-in. You run your own client.
- On your server, the step's text goes to Anthropic with your own key, as the section above says.
- The text of a task reaches your Claude Code as data, never as instructions.
- Contact details (e-mail, phone, address) are never sent. Only a name is sent, and only when a step's instruction asks for it.
- Your own Claude Code setup (hooks, other MCP servers, allowed tools) is outside Sidekick's control. Check it before you run steps.
- Set a spending limit with your provider as an outer guard. Sidekick's figures are estimates.

## If it does not work

| You see | What to do |
| --- | --- |
| The plan has changed | Approve the plan again in the Work room. |
| The step is not ready | An earlier step is still open, a run is active or waits for you, or the attempts are used up. |
| A run that stopped without a report | It can be replaced after 30 minutes. Start the step again. |
