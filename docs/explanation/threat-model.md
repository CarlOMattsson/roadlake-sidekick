# Threat model

A short model of what Roadlake Sidekick protects, from whom, where the trust boundaries are and which controls
hold them. It is a map for reviewers and reporters, not a guarantee; the code and tests are the maintained truth.
Report problems as described in [SECURITY.md](../../SECURITY.md).

Sidekick is a self-hosted system for **one owner**: one instance serves one person's records. There is no public
registration, no web sign-in and no cookie.

## Assets

| Asset | Why it matters |
| --- | --- |
| Records in PostgreSQL: journal text, contacts, tasks, projects, shopping lists | Personal and often sensitive content. The main asset. |
| Credentials: personal access tokens, OAuth grants, companion device credentials, the token pepper, backup keys, the license key | Possession is authority over the records. |
| Backups and snapshots | A full copy of the records outside the running system. |
| Derived memory in Hindsight (optional) | Facts extracted from the records; may be stored with a model provider chosen by the owner. |
| Logs, traces and telemetry | Must never become a second copy of the records. |
| The release artifacts: image, APK, signing identity, license public key | A tampered build bypasses every other control. |

## Actors

| Actor | Assumed capability |
| --- | --- |
| Owner | Fully trusted for their own instance; holds the host, the keys and the OAuth identity. |
| Internet attacker | Reaches the public MCP and companion endpoints; no credentials. |
| Holder of a stolen or leaked credential | A token, device credential or backup file, within what it was scoped to. |
| Malicious or manipulated model output and stored text | A model, a pasted web page or a contact note that tries to steer the host model into calling tools. |
| Other tenant or other user on the same host | Another local process or container without access to the secrets. |
| Compromised third party | Claude host, a model provider, a push server, a registry or a dependency. |
| Attacker with a compromised host | Out of scope: such a host holds the database and the keys. |

## Trust boundaries

1. **Internet to Sidekick.** The reverse proxy terminates TLS and is the only public entry. The API listens on loopback
   only in the shipped packages. MCP requests carry a bearer token or an OAuth session; companion requests carry a
   paired device credential.
2. **Claude host to Sidekick.** The host and its model are not trusted to decide authority. Each MCP tool checks owner,
   scope and observed version on the server. "Ask first" wording in a tool description is advice to the model, never a
   server check.
3. **MCP Apps rooms to the host.** The rooms run in the host's sandbox and reach the server only through the host
   bridge. They never hold credentials; app-only visibility grants no scope.
4. **Android app to Sidekick.** The app pairs once with a short-lived code, then holds its own scoped, renewable device
   credential in the Android Keystore. It is a separate credential from the MCP tokens and cannot be used as one.
5. **Application to database.** Runtime processes use the least-privilege `sidekick_app` role and cannot run DDL; only
   the migrator role changes the schema.
6. **Sidekick to optional services.** Hindsight (memory) receives text derived from the records and may call a model
   provider the owner configures; ntfy (push) receives content-free wake-ups. Both are off unless configured.
7. **Job package to the outside** (the optional `deploy/work` profile). Only the gateway container has a route out;
   every other service sits on internal networks, and the only published port is the gateway's, on loopback
   (`deploy/work/compose.yaml`; `test_only_the_gateway_has_a_route_to_the_outside` and
   `test_only_the_gateway_publishes_a_port_and_only_on_loopback` in `backend/tests/selfhost/work_package/`).
8. **Local process to the owner's identity.** The stdio entry point (`backend/src/sidekick/mcp/stdio.py`) carries no
   token: it acts as the owner named in `SIDEKICK_MCP_STDIO_OWNER_ID`, so whoever can start it is the owner.

9. **Build to user.** Images are pinned by digest, signed and accompanied by an SBOM; the updater verifies the
   signature before it replaces anything.

## Threats and controls

| Threat | Controls |
| --- | --- |
| Unauthenticated access to records | Authentication on every MCP and companion route; an allowlist of public paths; deny by default. |
| Privilege escalation across scopes or owners | Scopes and owner filtering are enforced in the shared application use cases, not in the transport or the UI; a stored scope the code no longer defines is dropped at verification; tests cover allow and deny for each tool. |
| Credential theft or replay | Tokens are stored only as keyed digests (HMAC with a server pepper) with a purpose column, so an MCP token and a device credential cannot be exchanged; expiry, revocation and last-used are checked on each call (for sign-in through GitHub, a successful check of the GitHub grant is reused for 300 seconds by default, `SIDEKICK_MCP_OAUTH_UPSTREAM_CACHE_SECONDS`, so a revoked grant can keep working that long unless the setting is lowered or the api container is recreated; an owner who is disabled is refused at once); device credentials last 30 days by default and renew themselves; pairing codes are redeemed atomically once. |
| Prompt injection through stored text or tool output | Stored text cannot select an actor, widen a scope or trigger another tool; writes are direct, owner-checked commands with versions and idempotency keys; the one AI-reviewed flow (the journal draft) needs the owner to finalize; destructive operations are trash and restore, and permanent deletion is not a public tool. |
| Leakage through logs, traces and errors | Structured logs use an allowlist of fields; titles, text, prompts, tokens and bodies are never logged; errors returned to clients are generic and carry a correlation id; tests prove redaction. |
| Resource exhaustion | Request body size and read-time limits, bounded batch sizes and page sizes, limits on device-credential renewals and test notifications, timeouts on outgoing calls. The model-visible tool list also has a fixed context budget, and its output schemas a ceiling, so tool definitions cannot grow past what a host puts in the model's context without a reviewed change (`backend/tests/contract/test_tool_context_budget.py`); the size of each tool's answer is bounded by the page and batch sizes above. |
| Data loss or silent corruption | Optimistic versions on writes, durable idempotency, append-only event ledger, trash before deletion, encrypted backups that are decrypted and checked again before they count, and a drill that restores them. |
| Stolen backup file | Backups and snapshots are encrypted with a key kept outside the backup directory; losing the key means losing the backups. |
| Exposure through the memory service | Hindsight is optional; per-source switches, pause and per-record exclusion are owner controls; journal text and other derived input go to the configured model provider, which the owner chooses. |
| Tampered release or dependency | Digest-pinned images, signed images and checksums, SBOM, dependency and image scanning, pinned CI actions, secret scanning, a license public key that is checked at build time. |
| Egress or path smuggling through the model gateway | The gateway is the only way out and allows one upstream plus the addresses the owner lists in `SIDEKICK_WORK_ALLOW`, each as TCP passthrough on its own port. On the model listener the raw path is judged before any decoding: a path containing `%`, `;`, `\` or a `..` segment is refused with 403, `//` and `/./` are folded, and the base path must match as a whole segment (`/v1` or `/v1/...`, never `/v1x`); nothing is logged (`deploy/work/gateway.haproxy.cfg`; `test_the_live_gateway_refuses_paths_that_could_be_read_as_another_path`, `test_the_allowlist_becomes_passthrough_listeners_and_network_aliases` and `test_the_gateway_is_locked_down` in `backend/tests/selfhost/work_package/`). |
| Docker socket access as owner access | Not a control but an assumption: whoever can run `docker exec` on the host can start the stdio process and holds every scope of the enabled rooms, so access to the Docker socket is owner access. Keep it to the owner's own account; rooms that are switched off have no tools (`docs/operate/work-laptop/README.md`; `test_a_room_that_is_off_has_no_tools_and_cannot_be_called` in `backend/tests/mcp/test_stdio.py`). |
| Stdio acting as the owner without a token | The process refuses to start when the owner is unset, is not a UUID, is not a user or is disabled, and re-checks the owner on every request, so disabling the account stops a running session; it is trusted exactly as far as the database credentials in its environment (`backend/src/sidekick/mcp/stdio.py`; `test_a_missing_owner_stops_the_process_with_a_clear_message`, `test_an_owner_who_is_not_a_user_stops_the_process`, `test_disabling_the_owner_stops_a_session_that_is_already_running` in `backend/tests/mcp/test_stdio.py`). |
| Misconfiguration | The packages bind to loopback by default, run as non-root with read-only filesystems where practical, and refuse unsafe settings at start. |

## Tool list budget, sign-in cache and dependency review

Three controls are easy to overlook because they sit between features rather than inside one.

### The model-visible tool list has a fixed size

Every tool a host shows the model costs its name, description and input schema in the model's context. If the list
grew without anyone noticing, tool descriptions would crowd out the owner's own conversation and a long, attacker-
influenced description would have more room to steer the model. `backend/tests/contract/test_tool_context_budget.py`
estimates the cost from the reviewed tool snapshot (characters divided by 3.5), counts only the tools the model
sees (tools meant for the rooms alone are not counted), and fails when the total, the longest description or the
combined size of the output schemas passes a fixed ceiling. The ceiling is a guard against silent growth, not a
target: raising it takes a reviewed reason in the same change, and the failure message lists every tool with its
sizes so the cause is easy to find.

### The sign-in cache and what it means for revocation

When you connect Claude through GitHub sign-in, Sidekick asks GitHub whether the access grant is still valid. A
successful answer is reused for 300 seconds by default (`SIDEKICK_MCP_OAUTH_UPSTREAM_CACHE_SECONDS`, 0 to 3,600;
0 checks on every request), so that every tool call does not need a round trip to GitHub. The consequences:

- If you revoke the grant at GitHub, it can keep working for Sidekick for up to the configured time. Lower the
  setting, or recreate the api container (which empties the cache), if you need an immediate cut-off.
- Only that check is cached. Whether the owner account is still enabled is checked on every request, so disabling
  the account takes effect at once.
- The list of allowed GitHub identities is read at startup, so removing an identity needs a restart.
- Personal access tokens and device credentials are not affected: they are checked against Sidekick's own database
  on each call.

### Reviewing the frozen MCP library and other dependencies

`fastmcp` is pinned to an exact version and left out of automatic update proposals, because it carries the tool and
schema contract the rooms and clients rely on. A frozen dependency still collects security fixes it does not get,
so review it on a schedule: once a quarter (and sooner when a security advisory names it), read the release notes
and advisories of `fastmcp`, `mcp`, `httpx`, `httpx2` and the other pinned runtime libraries, and decide per item
whether to upgrade or to record why not. An upgrade of `fastmcp` goes through the contract tests first (the
generated tool list, the tool context budget above and the authentication tests) and is never merged on a green
unit run alone. Image and dependency scanning in the release process covers known vulnerabilities between reviews;
the quarterly review covers the ones that scanners do not flag and the drift that frozen versions invite.

## Phone pairing, credential renewal, push and backups

The sections below take the four flows that hold a long-lived secret or leave the server and apply the same
questions to each: what is worth protecting, who can attack it, and which control exists today with the file that
implements it. Everything here is about one owner's instance; the tests named are the evidence.

### Pairing the Android app

Assets: the pairing code (`rspair_` prefix, 256 bits, valid 10 minutes, usable once) and the device credential it
turns into. The pairing link `sidekick://pair?server=<url>&code=<code>` carries the code, so anyone who sees the
link or the QR code before it is used can pair.

| Threat | Existing control |
| --- | --- |
| Guessing a code | 256 bits of randomness; only the keyed digest is stored (`backend/src/sidekick/companion/service.py`). |
| Replaying or racing a code | The exchange is one atomic `UPDATE ... WHERE consumed_at IS NULL AND expires_at > now`, so exactly one caller wins; unknown, expired, used and malformed codes all answer the same 401 `pairing_invalid`, and an over-long input is refused before any digest (`CompanionDeviceService.exchange`). |
| Hammering the public pairing route | Only `POST /companion/v1/pair` is public for the companion adapter, by exact method and path (`backend/src/sidekick/api/public_surface.py`); failed exchanges spend a budget of 30 a minute and then every attempt gets 429 before any database work (`backend/src/sidekick/api/companion.py`, test in `backend/tests/api/test_companion.py`). A refused exchange writes no audit row, so the append-only log cannot be filled by a stranger; the route counts it as a content-free metric instead. |
| A link opened by another app or page | The deep link only fills in the pairing screen, which asks before it pairs; it never acts by itself (`frontend/android/app/src/main/AndroidManifest.xml`). Pairing requires the owner to run the pairing command on the server first (`backend/src/sidekick/companion/cli.py`; link format tested in `backend/tests/unit/test_companion_pairing_link.py`). |
| Stolen phone or backup of the phone | The credential is kept as an encrypted record whose AES-256-GCM key is generated inside the Android Keystore and cannot be exported; the app opts out of Auto Backup and device-to-device transfer (`frontend/android/app/src/main/kotlin/com/roadlake/sidekick/companion/KeystorePairingStore.kt`, `AndroidManifest.xml`). The owner can revoke the device on the server at any time (`CompanionDeviceService.revoke_device`). |
| A device credential used as an MCP token, or the reverse | Tokens carry a `purpose`; the verifier checks it, and the device scope set is closed (`COMPANION_SCOPES`). |
| Pairing for a user who has since been disabled | The code is still consumed, no device is created, and the denial is audited (`exchange`, reason `user_inactive`). |

Residual: a code that is shown on a screen or sent through a chat can be read by whoever sees it within its ten
minutes. The pairing command prints it once; treat it like a password and revoke an unexpected device.

### Renewing the device credential

Assets: the device credential (30 days by default, at most 90) and the ability to extend it.

| Threat | Existing control |
| --- | --- |
| A credential that never expires | It does not: the device renews inside the last 7 days only (`RENEWAL_WINDOW`), earlier attempts answer 409 with the time to retry; a lapsed credential means pairing again (`CompanionDeviceService.renew`, `backend/tests/api/test_companion_renew.py`). |
| A stolen credential kept alive indefinitely by renewing | Renewal needs the current credential; at most 5 renewals succeed per 24 hours and then 429 with `Retry-After`; revocation and owner deactivation stop renewal; every renewal is audited without any token or digest. The owner sees the expiry in the device list and can revoke. |
| A lost response leaving the device without a credential | The replaced credential keeps working for at most 10 minutes (`RENEWAL_GRACE`) or until the new one is first used, and may renew again once. This is a deliberate trade-off: a stolen old token could also use the window, so such a renewal is audited with `reason="via_previous_token"`. |
| Two renewals at the same moment | The device row is locked and the presented token is checked again under the lock, so only the last token issued is valid (`test_two_simultaneous_renewals_leave_one_valid_new_token`). |
| Token or digest in logs | Audit rows and logs carry only closed-vocabulary events and the device id (`test_a_renewal_is_audited_without_a_token_and_logs_carry_no_secret`). |

Residual: while a credential is valid and not revoked, whoever holds it has the device's scopes. Keep the scopes
small and revoke devices you no longer use.

### Push and the notification server

Assets: the UnifiedPush endpoint of each phone (a URL on the notification server, effectively a capability to push
to that phone), the optional bearer token Sidekick uses to publish to your own server, and the reminder timing
that a push reveals.

| Threat | Existing control |
| --- | --- |
| Records leaking through the push channel | A push body is one of two fixed values (`{"k":"w"}` or `{"k":"r"}`); it contains no title, text or id, and the phone fetches the real data from the authenticated companion API after the wake (`backend/src/sidekick/companion/push_worker.py`, `push_outbox_store.py`). Reminders are shown by the phone itself, never composed on the push server. |
| Server-side request forgery through a registered endpoint | An endpoint must be https, port 443, no userinfo, no IP literal, at most 512 printable ASCII characters and on the owner's allowlist of hosts (default: the public ntfy.sh server); it is validated again before every send, so removing a host takes effect at once. The worker follows no redirects, times out after 10 seconds and never reads the response body (`backend/src/sidekick/companion/push.py`, `backend/tests/api/test_companion_push.py`, `backend/tests/api/test_companion_push_delivery.py`). |
| Topic or endpoint leakage | Endpoints, topics and payloads are never logged or audited; a subscription is identified in logs by its host only, and span scrubbing covers exceptions (`backend/src/sidekick/shared/observability/setup.py`). A person who learns a topic can read or send content-free wakes for that phone, but cannot read records or act as the device; the damage is noise and a battery cost. The self-hosted notification server denies all access by default, lets Sidekick write and the phone read only the `up*` topics, has no web app, no accounts, no on-disk cache and logs at `warn` so no topic is written (`deploy/selfhost/ntfy/server.yml`). On the shared public server the topic name is the only secret. |
| Credential sent to the wrong host | The publish token is a `SecretStr` and is attached only when the endpoint's host equals the configured auth host exactly; every other host gets no credentials (`backend/tests/unit/test_push_worker_auth.py`). |
| Revoked or expired device still receiving wakes | The worker checks the device credential and the owner before each send and revokes the subscription instead of sending. |
| Runaway sending | Wakes are coalesced per subscription, there is a minimum interval, retries back off with a cap, and a 429 blocks the host in memory rather than hammering it (`push_outbox_store.py`, `push_delivery.py`). |

Residual: the notification server learns that a phone was woken and when, and its IP address. The shared server is
a third party; use your own for anything beyond a trial.

### Backup encryption

Assets: the backup files and database snapshots (a full copy of the records), and the key that opens them.

| Threat | Existing control |
| --- | --- |
| A backup file read by someone else | Owner backups are authenticated Fernet encryption of the whole export; the envelope holds no owner data, the directory is created `0700` and files `0600` (`backend/src/sidekick/backup/bundle.py`). Database snapshots taken by the update and work scripts use the same cipher through one implementation that reads the key from the environment, never from the command line, and prints nothing unless the whole input decrypted (`deploy/selfhost/snapshot_crypto.py`). |
| The key stored next to the backups | Sidekick never persists the key; it comes from the process environment or a secret store, and a missing or malformed key refuses to start a backup (`backend/src/sidekick/shared/config/`, `backend/src/sidekick/backup/bundle.py`). Keep the key somewhere other than the backup directory; losing it loses the backups. |
| A silently broken backup | The export is checked as restorable before anything is written, the file is read back and decrypted after it is written, and a failure deletes the file and is reported as a refusal; the drill restores a backup into a throw-away stack (`backend/tests/unit/test_backup.py`, `tools/drill.sh`). |
| Tampering | Fernet is authenticated: a changed byte or a wrong key fails to decrypt and produces no output. |
| Disk exhaustion or runaway retention | Free space is checked before a backup, and retention by count and age always keeps a minimum (`ensure_free_space`, `prune_backup_files`). |

Residual: encryption and decryption happen in memory, so a very large database needs memory in proportion. The key
protects backups only as well as the place it is kept; a copy of the key and a backup together are the whole
database. Off-server copies and key custody are the owner's responsibility.

## Residual risks and non-goals

- A compromised host, database or key store defeats every control above.
- The owner's Claude account, the model provider and the push server are trusted to the extent the owner connects
  them; Sidekick limits what it sends but cannot control what they retain.
- Journal text is sent to Claude by design; with memory enabled, derived text also goes to the chosen model provider.
- A prompt-injected model can still use the scopes the owner granted it. Grant the narrowest scopes that the work
  needs.
- Backups are encrypted in memory, so very large databases need more memory than disk; off-server copies are the
  owner's responsibility.
- The macOS path has not been tried yet; see the status box in the [README](../../README.md).
