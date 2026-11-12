# ADR-004: Keep executable truth and explanatory documentation distinct

- Status: Accepted; the ADR lifecycle section was clarified on 2026-11-10
- Date: 2026-08-23
- Owners: Sidekick application maintainers

## Context

Sidekick has code, migrations, generated contracts, tests, operational guides, ADRs and a decision
log. These artifacts serve different purposes, and stale planning prose has previously made it
difficult to tell what is implemented.

## Decision

Executable code, migrations, generated contracts, tests, `README.md`, `QUICKSTART.md`, and reviewed
runtime configuration are the maintained implementation truth. ADRs and `docs/decisions/log.md`
explain current choices and constraints. Explanatory maps or dated reviews, where they exist, are
decision aids and never prove that a feature exists.

Every new durable cross-cutting decision gets an ADR in `docs/decisions/adr/` and an entry in
`docs/decisions/log.md`. An ADR cites its evidence as file paths in this repository, not as
commit hashes or documents outside it. Where uncertainty matters, it is labelled `KNOWN`, `ASSUMED`,
`OPEN`, `DEFERRED` or `REJECTED`.

ADR lifecycle:

- **Accepted** ADRs are not rewritten to make history appear current. A later decision that
  replaces one marks it in the status line as `Superseded by <decision>` and states what replaces
  it; the superseded ADR stays in place, readable, and is listed as superseded in the decision log.
- An accepted ADR whose decision is unchanged may be **revised** to describe the delivered state
  instead of the plan. The revision is dated in the status line, and the decision itself must not
  change; a changed decision needs a new decision entry instead.
- Planning material (milestones, task lists, open questions of the moment) belongs in the plan,
  not in the ADR.

## Consequences

- A reader can identify the authoritative source before acting on a claim.
- Guides name the files they describe, but they do not duplicate every implementation detail.
- Historical decisions remain historically honest, while their current reading is recorded in
  their status line and in the decision log.

## Evidence

- `docs/decisions/log.md` and the other ADRs in `docs/decisions/adr/`
- `README.md` and `QUICKSTART.md`
