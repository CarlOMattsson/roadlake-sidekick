"""What the MCP request says about the connection it came through, for a run to remember.

A run notes which kind of credential claimed it and, when the transport keeps one, a keyed hash of
the MCP session. The session id itself is never stored, logged or returned.
"""

from fastmcp.server.dependencies import get_access_token, get_http_request

from sidekick.automations.domain.runs import CredentialKind
from sidekick.mcp.auth import OAUTH_CLIENT_ID


def request_session_id() -> str | None:
    """The id the client's MCP session has, or `None` outside an HTTP request or when the
    transport has no session (a client that opens a connection per request has none to keep)."""

    try:
        value = get_http_request().headers.get("mcp-session-id")
    except RuntimeError:
        return None
    return value or None


def request_credential_kind() -> CredentialKind:
    """`oauth` for a connector's session, else a personal token (also on stdio)."""

    token = get_access_token()
    if token is not None and token.client_id == OAUTH_CLIENT_ID:
        return CredentialKind.OAUTH
    return CredentialKind.TOKEN
