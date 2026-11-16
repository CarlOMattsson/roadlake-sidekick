# Run AI steps with Claude Code

[Svenska](ai-steps.sv.md)

<!-- description: Let your own Claude Code run the AI steps of an approved task, then review what it writes. Sidekick never sees your Claude sign-in. -->

Some steps of a task can be done by AI: a first draft, research, a summary, a checklist. You approve the plan, your own Claude Code runs the AI steps, and every result waits for you to review it. An AI step only makes text inside Sidekick. Sending, buying, deleting or publishing is always a step that you do yourself.

## The flow

1. **Mark the task as possible with AI.** Open the ⋯ menu on the task in the Work room, or ask Claude. The mark costs nothing.
2. **Ask Claude to plan the task.** Each step is marked "You" or "AI". Each AI step has a short instruction: the goal, when it is done, the result format, the tools it may use, a budget, and when it must stop and ask you.
3. **Approve the plan in the Work room** with one click. The approval covers exactly this plan. If the plan changes afterwards, nothing runs until you approve it again.
4. **Run the AI steps** with Claude Code, as described below.
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
| `SIDEKICK_AI_MAX_ATTEMPTS_PER_STEP` | 3 | Attempts at one AI step |
| `SIDEKICK_AI_CLAUDE_CODE_STARTS_PER_DAY` | 50 | AI steps your Claude Code may start per day |

These are set like the other settings; see the [Configuration reference](../reference/configuration.md). `SIDEKICK_AI_LOCAL_MODELS_EXEMPT_FROM_CAP` takes runs on a local model, which cost nothing, out of the money caps.

The cost that Claude Code reports is an estimate. Sidekick stores it with each run but does not count it against the money caps, because a plan sign-in is not billed per call. The protection there is the number of attempts and starts. The money caps apply once a server runner exists. That runner is planned and not built yet.

## What to know before you run

- Sidekick never starts Claude Code and never receives your Claude sign-in. You run your own client.
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
