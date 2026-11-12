"""Shared test helpers moved out of `tests/selfhost/test_selfhost_ntfy.py`."""

# Paths that must never reach the ntfy service through Caddy.
NOT_NTFY_PATHS = [
    "/",
    "/v1/health",
    "/v1/account",
    "/v1/webpush",
    "/_matrix/push/v1/notify",
    "/mcp",
    "/companion/v1/device",
    "/.well-known/oauth-protected-resource",
    "/up",
    "/uploads",
    "/upabcdef",  # shorter than the 8-character minimum after "up"
    "/upabcdefgh12,other",  # ntfy's multi-topic subscription
    "/upabcdefgh12/../v1/account",
    "/upabcdefgh12/publish",
    "/upabcdefgh12/",
    "/UPabcdefgh12",
    "/other/upabcdefgh12",
    "/ntfy/upabcdefgh12",
    "/v1/../upabcdefgh12x/y",
]


NTFY_PATHS = [
    "/upabcdefgh12",
    "/upabcdefgh12/json",
    "/upabcdefgh12/ws",
    "/upabcdefgh12/sse",
    "/upabcdefgh12/raw",
    "/upabcdefgh12/auth",
    "/up" + "A1_-" * 16,
]
