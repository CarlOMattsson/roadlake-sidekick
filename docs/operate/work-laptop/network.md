# How the network is closed

[Svenska](network.sv.md)

<!-- description: The work package's containers have no route out. This page explains how the network is closed and how to allow more addresses than the model server. -->

The work package's containers have no route out. This page explains how the network is closed and how to allow more addresses than the model server.

## How the network is closed

All Sidekick containers sit on Docker networks that have no route out. The only exception is a pinned HAProxy
container (`gateway`) that forwards to exactly one address, the model server in `work.env`, and only under its base
path (anything else gets 403). It also publishes the HTTP surface of MCP on `127.0.0.1` only (Claude Desktop does not
use it; it answers 401 without a token and no tokens are issued any more). It works the same on any Docker host and
needs no firewall changes. The laptop's trust store is used for an https model server.

## Allowed addresses

Besides the model server nothing can be reached. To allow more (for example a separate embeddings server), list
host names with ports in `SIDEKICK_WORK_ALLOW=embed.company.lan:443,files.company.lan:8443` (or answer the guide's
question). Each entry becomes a plain TCP pass-through on the gateway, so the client keeps the real name and checks
the real certificate. Limits: host names only (no IP addresses), and every entry needs its own port (also different
from the model server's and from 8765). Everything else stays blocked. The `status` check prints what is reachable.
