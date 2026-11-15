# Webhooks for Home Assistant, Tasker and similar tools

[Svenska](webhooks.sv.md)

<!-- description: Let home or phone automation add a shopping item or a task through a token-protected endpoint, with one token per integration. -->

Let home or phone automation push one small fact into Sidekick: a kitchen voice assistant adds milk to the shopping list, or Tasker adds a task when you leave work. The webhook entrance is narrow on purpose. It has two fixed actions, one token per integration, and no way to read anything back.

| Request | What it does | Scope the token needs |
| --- | --- | --- |
| `POST /webhooks/v1/shopping-items` | Adds one item to a shopping list. Without `list_id` the item goes to your oldest active list. | `webhook:shopping:add` |
| `POST /webhooks/v1/tasks` | Creates one task with a title and an optional due date. | `webhook:tasks:create` |

## Turn it on

The entrance is off until you set `SIDEKICK_WEBHOOKS_ENABLED=true` (in `selfhost.env` on a self-hosted server, otherwise in the environment or `.env`) and restart the API. While it is `false`, the routes are not registered at all and answer 404.

The API answers these paths itself, so Home Assistant on the same network can call it directly. For a phone away from home the sample `deploy/selfhost/Caddyfile.example` forwards exactly these two paths and nothing else under `/webhooks/`.

## Create a token

One token per integration, so you can revoke one without touching the others. From a checkout:

```bash
uv run --project backend python -m sidekick.webhooks.cli create --label "Home Assistant" --scope webhook:shopping:add
```

Self-hosted, from `deploy/selfhost`:

```bash
docker compose --env-file selfhost.env exec -T api python -m sidekick.webhooks.cli create --label "Tasker" --scope webhook:tasks:create
```

- `--scope` is required and repeatable. No scope is implied.
- `--expires-in-days` sets the lifetime (default 365, at most 730). A token always expires.
- `--rate-limit` sets the calls per minute for this token (default 30, at most 600).
- Without `--user-id` the command uses the only active owner and stops if there is more than one.

The command prints the token (`rsw_...`) once, as JSON. Only a keyed digest and the first ten characters are stored, so nobody can show it to you again; create a new token if you lose it. Treat it like a password.

List tokens (never the token itself) and revoke one:

```bash
uv run --project backend python -m sidekick.webhooks.cli list
uv run --project backend python -m sidekick.webhooks.cli revoke --token-id <id>
```

A revoked or expired token stops working on its next call, and so does every token of a user that is disabled.

## The request

```http
POST /webhooks/v1/shopping-items
Authorization: Bearer <token>
Idempotency-Key: <8 to 128 characters, new for each action>
Content-Type: application/json

{"name": "Milk", "quantity": 2, "unit": "l", "note": "organic", "list_id": "<optional list id>"}
```

```http
POST /webhooks/v1/tasks
Authorization: Bearer <token>
Idempotency-Key: <8 to 128 characters, new for each action>
Content-Type: application/json

{"title": "Call the dentist", "due": "2030-05-17"}
```

- Shopping item: `name` is required (up to 200 characters); `quantity` (default 1), `unit`, `note` and `list_id` are optional. If you have no active list the call answers 404; a webhook never creates a list.
- Task: `title` is required (up to 200 characters). `due` is optional: a date (`2030-05-17`) means the end of that day in your time zone, and a datetime with an offset (`2030-05-17T08:30:00+02:00`) is used as given.
- Other fields are refused with 422. The body may be at most 8 KiB.
- `Idempotency-Key` is required. Send the same key and the same body again and you get the first answer and nothing is written twice, so an automation may retry after a lost answer. The same key with a different body answers 409.
- Success is `201` with the id of what was written: `{"list_id", "item_id"}` or `{"task_id"}`.
- Each token has its own rate limit per minute; over it the answer is `429` with `Retry-After`. The limit is kept per API process.

Refusals use one closed problem body (`code`, `title`, `status`, `correlation_id`, and for 403 and 409 a `reason`) and never repeat what you sent. 401 means the token is missing, unknown, expired or revoked, 403 `scope_missing` that the token lacks the scope for this action.

The writes are ordinary shopping and task writes: they show up in the activity trail like anything else you add. The request log carries only the operation name, the outcome and the token's record id. It never carries the token, the idempotency key or what you sent.

## Home Assistant

Add a `rest_command` to your Home Assistant configuration, with the token in its secrets file (for example `sidekick_webhook_token: "Bearer <token>"`):

```yaml
rest_command:
  sidekick_add_shopping_item:
    url: "https://<your-domain>/webhooks/v1/shopping-items"
    method: post
    headers:
      Authorization: !secret sidekick_webhook_token
      Idempotency-Key: "ha-{{ now().timestamp() }}-{{ name | slugify }}"
      Content-Type: application/json
    payload: '{"name": {{ name | tojson }} }'
    timeout: 10
```

Call it from an automation or a script with `action: rest_command.sidekick_add_shopping_item` and `data: {name: "Milk"}`. A task works the same way against `/webhooks/v1/tasks` with `{"title": ...}`.

## Tasker

Add an action Net, HTTP Request:

- Method `POST`, URL `https://<your-domain>/webhooks/v1/tasks`
- Headers (one per line): `Authorization: Bearer <token>`, `Idempotency-Key: tasker-%TIMES` and `Content-Type: application/json`
- Body: `{"title": "Check the post", "due": "2030-05-17"}`

`%TIMES` is the current time in seconds, so each run gets a new key. Keep the token in a Tasker variable that is not shared in a profile export.

## If it does not work

| You see | Likely cause |
| --- | --- |
| `404` on the path | `SIDEKICK_WEBHOOKS_ENABLED` is not `true` (or the API was not restarted), or the reverse proxy does not forward the path. A `404` with `not_found` and no `reason` can also mean you have no active shopping list. |
| `401` | The token is wrong, revoked or expired, or the header is not `Authorization: Bearer <token>`. |
| `403` `scope_missing` | The token was created without the scope for this action. Create a new token with the scope. |
| `409` `idempotency_key_reused` | The same `Idempotency-Key` was used with a different body. Use a new key for each action. |
| `422` | The body has a missing or unknown field, a value that is too long, or no `Idempotency-Key`. |
| `429` | The token's rate limit is spent. Wait the number of seconds in `Retry-After`, or create a token with a higher `--rate-limit`. |
