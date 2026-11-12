# Decision archive

Decisions that have been replaced. They are kept for traceability only and do not describe how Sidekick works
today: the [decision log](log.md) holds the decisions in force, and each entry here names the decision
that replaced it. IDs are stable and never reused.

### D-036 - Records created from a conversation keep a generic origin link (removed)

Status: Superseded by D-084; the chat engine it served was removed in 0.1.0.
Each record created from an approved conversation proposal kept its origin in one generic `entity_origins`
relation, with no foreign key to the target, instead of one origin table per kind. It was the only exception to
the rule against generic link tables between domain records. The table is not in the 0.1.0 baseline. Why: an
approved proposal stays traceable to the conversation that produced it.

### D-051 - Claude with MCP Apps as primary chat surface

Status: Superseded by D-052 and D-053.
An earlier prototype direction to reuse one React view in a standalone app and in an MCP App. The
standalone part was dropped by D-052.

### D-056 - Owner review of proposals over MCP (historical)

Status: Superseded by D-064 for the MCP surface.
Four review tools were once delivered so the owner could confirm or reject proposals from an MCP App.
They were later removed, and the entry is kept only as history.

### D-085 - Home Assistant voice entrance on loopback

Status: Superseded by D-088 (originally accepted 2026-11-05; removed 2026-11-11).
Home Assistant reaches Sidekick through its own narrow voice entrance (`/voice-mcp`, a separate process bound
to loopback), not through the public `/mcp`. Its MCP client cannot send a personal token, so the entrance has
no credential: it serves only plain local requests, acts as one configured owner that must be active, and
exposes seven tools (brief, agenda, shopping lists, new tasks) with narrow scopes and no deletion. The whole
computer is trusted for this entrance; the protection is against the network outside it. Why: voice at home
without widening the public surface.

### D-086 - Direct-channel measurement probe

Status: Superseded by D-088 (originally accepted 2026-11-05; removed 2026-11-11).
The MCP App may later talk to Sidekick directly instead of through the host, for speed. The first step is
only a measurement: with `SIDEKICK_APP_DIRECT=probe`, on an instance labelled `sandbox`, a data-free ping
route and an app-only tool compare the two paths' timings and log closed values only. The default `off`
registers nothing. Any real direct channel needs its own design and review first.
