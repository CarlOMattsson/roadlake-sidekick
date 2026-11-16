# Security and privacy in plain words

[Svenska](security-and-privacy.sv.md)

<!-- description: Who sees what when you use Sidekick – you, Claude, the model provider for memory, GitHub, the ntfy server and the website's host. -->

This page says plainly who sees your data and when. It promises no more than the code can show. The technical walk-through is in the [threat model](threat-model.md).

:::caution[Self-hosting does not keep content away from Claude]
To self-host means to run Sidekick on a server you control. Your records are stored there. But what Claude may read in order to help you leaves the server and is shared with Claude.
:::

## Who sees what

| Who | What | When |
| --- | --- | --- |
| You | Everything. You hold the server, the database and the keys. | Always |
| Claude | What the connector's scopes allow, including journal text if `journal:read` is granted. Also what you type and see in the conversation. | When Claude calls a tool or shows a room |
| The model provider for memory | Text from the sources you switched on: journal, contacts, projects and tasks. Never contacts' email, phone or address. | Only if you turned memory on |
| GitHub | That you sign in to your server. Sidekick asks GitHub for nothing beyond who you are. | When you sign in the connector |
| Anthropic, for AI steps on your server | The brief of each step you run: the task's title and description, the step's instruction, titles of actions, the project's title, and contact names or reference titles if the step allows it. Never e-mail, phone, address, journal text or memory. | Only if you turned the `ai` profile on and press Run |
| The ntfy server | That a phone was woken, when it happened, and the phone's IP address. No content. | Only if you turned reminders on |
| The website's host (GitHub) | What a web server sees, such as your IP address, under GitHub's own policy. | When you visit this website |

## Where your data lives

Your records live in PostgreSQL on your server: tasks, projects, journal, contacts and shopping lists. Sidekick has no central service that receives them. One instance serves one owner. There is no public registration.

## What Claude sees

A scope is a permission that the server checks on every call. You set which scopes the connector gets, and Claude cannot go beyond them. The example configuration gives read access only, to projects, tasks, contacts and shopping, and no access to the journal.

What Claude reads within its scopes leaves your server. It is then covered by Anthropic's terms, not by anything Sidekick controls. So grant the narrowest scopes that are enough for what you want to do.

One more thing is worth knowing. A text that Claude reads, such as a pasted web page, can try to steer Claude. Claude can still only use the scopes you granted.

## Memory

Memory is optional and off until you turn it on. When it is on, the Hindsight service sends text to the model provider you configured yourself. You can pause memory, switch off a source and keep a single record out. [Read about Control and memory](../guide/control-and-memory.md).

On a work laptop, the containers (including memory's calls) reach only your company's own model server. Claude Desktop is still an external service: what is shown or typed in the conversation, and the names, arguments and results of the Sidekick tools Claude calls (task titles, contact names, dates), are shared with Claude.

## No telemetry

Sidekick sends no telemetry and no analytics. The server only contacts the services you set up yourself: GitHub for sign-in, an ntfy server for reminders, a model provider for memory and, if you turned it on, Anthropic for AI steps you run on the server. Sidekick calls no language model on its own: a call is made only when you press Run on an approved step.

## AI steps on your server

This section applies only if you turned on the `ai` profile. Then an approved AI step can run on your server: you press Run in the app, and the container `ai-worker` makes a call to the Anthropic API. [Run AI steps](../operate/ai-steps.md) explains how to set it up.

- **The key.** Your Anthropic API key reaches `ai-worker` only, as a file. It is never stored in the database, never written to a log or a trace, and never returned by any tool. In production the API and the other workers refuse to start if they find the key in their environment.
- **The route out.** `ai-worker` is the only container on its own network, `ai`, which is the one outbound route to the internet. It shares no network with Hindsight or ntfy. The address of the API and the key are fixed in the code, so no environment variable can send the key elsewhere.
- **What is sent.** The step's brief goes to Anthropic under Anthropic's API terms: the task's title and description, the step's instruction, the titles of the task's actions, the project's title and, if the step allows it, the names of contacts and the titles of references. Never e-mail, phone, address, journal text or memory.
- **Prompt injection.** A text in a task can try to steer the model. Four things limit what that can do. The approved plan is the only source of instructions, and the server writes it. The owner's text is fenced off as data and stripped of control characters. The model has no tools: it cannot read, write, browse or send anything. Its answer must be strict JSON that the server checks, and the server only stores it as text for you to review. Sidekick does not try to detect injections with filters.
- **Money.** The worker reserves the most a call can cost before it makes the call, under one lock per owner, and settles the real cost afterwards. Caps apply per step, per task and per month. A call with an unknown outcome is booked at its reserved cost. [Run AI steps](../operate/ai-steps.md) has the details.
- **Telemetry.** The Anthropic SDK can emit OpenTelemetry spans and trace headers. Sidekick turns that off in the code and in the container, so no trace header or content leaves the process. Logs and telemetry from the worker hold ids, states and counts, never text.

## Logs

The logs hold no user content and no credentials. Titles, text and keys are never written there. Errors sent to a client are generic and carry an id that you can search for in the log.

## The license key

The license key is checked offline against a public key. Sidekick contacts no server to check it. The key carries the name of the licensee, and the name is shown in the app. Do not share your key.

## The phone

The Android app is paired with a code that works once and for ten minutes. The phone then gets its own credential, which is stored encrypted on the phone and is left out of the phone's backups. You can revoke it from the server at any time.

Reminders are sent as wake-ups with no content. The phone fetches the content from your server by itself. On the public ntfy server the topic name is the only secret, so use your own ntfy server for anything beyond a trial.

## Backups

Backups are encrypted once you have turned on the backup profile and created a key. Without the key they cannot be read. Keep the key somewhere other than the server, and keep a copy of the backups off the server. Anyone who has a backup and its key can read all of your records.

## What Sidekick does not protect against

- A server, a database or a key store that someone has broken into.
- What Claude, the model provider or the ntfy server retain. Sidekick limits what is sent but does not control what they keep.
- Someone who holds a valid credential. Revoke phones and access that you no longer use.

Sidekick 0.1.0 is the first version. It is in daily use with Claude, with the Android app on a real phone and on Linux. macOS has not been tried yet.

## Report a vulnerability

Report vulnerabilities privately, not in a public issue. [Read how to report a vulnerability](../../SECURITY.md).

## This website

The website has no cookies, no tracking and no third-party scripts. Search runs in your browser against an index that ships with the site. Your choice of light or dark theme is saved in your browser and nowhere else. GitHub hosts the website and may log IP addresses under its own policy.
