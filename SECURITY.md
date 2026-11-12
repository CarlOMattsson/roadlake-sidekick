# Security policy

[Svenska](SECURITY.sv.md)

## Reporting a vulnerability

Please report vulnerabilities **privately via the repository's security advisory feature** (the "Security" tab,
then "Report a vulnerability"). Do not open a public issue, pull request or discussion for a suspected
vulnerability, and do not post exploit details, tokens, logs with user content or real data anywhere public.

If that feature is not available on the repository, open an issue that says only that you have a security
report and want a private channel, with no details, and the maintainer will arrange one.

Include what you found, the version or commit, the steps to reproduce it, and the impact you expect. Use test
data only. Roadlake Sidekick is maintained by one person, so no response time is guaranteed; you will get an
acknowledgement, and fixes are coordinated with you before details are published.

## Supported versions

Only the **latest release** (and the current `main` branch) receives security fixes. Please check that the issue
still exists there before you report it.

## Threat model

What Sidekick protects, from whom, and which controls hold the boundaries is summarised in the
[threat model](docs/explanation/threat-model.md) (English).

## In scope

- Authentication and authorization: tokens, scopes, owner filtering, the MCP and companion endpoints,
  OAuth and pairing flows.
- Leaks of user content or credentials through logs, traces, telemetry, error messages or responses.
- Injection and unsafe handling of input in the backend, the MCP Apps rooms and the Android app.
- Weaknesses in the self-hosting package under `deploy/selfhost/` (default configuration, update and
  backup scripts, exposed ports).
- Flaws in how license keys are verified that let an unissued key be accepted. The licensor's public verification key is built into the repository (`backend/src/sidekick/license/public_key.py`); a public key is not a secret, and an instance can override it with `SIDEKICK_LICENSE_PUBLIC_KEY`.

## Out of scope

- Findings that need an already-compromised host, a stolen unlocked device or a leaked secret that you
  configured yourself.
- Denial of service by sheer volume, and missing hardening on infrastructure you operate yourself
  (your reverse proxy, DNS, firewall).
- Reports about third-party services you connect, such as Claude, a model provider or a push server: report
  those to the respective vendor.
- Social engineering, and automated scanner output without a demonstrated impact.
- The license notice itself: the unpaid notice is a documented feature, not a vulnerability.

Never commit populated `.env` files or credentials. If you find a secret in the repository history, report it
privately as above.
