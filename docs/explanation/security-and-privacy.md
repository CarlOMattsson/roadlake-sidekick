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

Sidekick sends no telemetry and no analytics. The server only contacts the services you set up yourself: GitHub for sign-in, an ntfy server for reminders and a model provider for memory. Sidekick calls no language model on its own.

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
