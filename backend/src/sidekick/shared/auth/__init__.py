"""Personal-token authentication for MCP clients and companion devices."""

from .service import (
    ALL_SCOPES,
    COMPANION_SCOPES,
    MCP_SCOPES,
    OPT_IN_SCOPES,
    TOKEN_PURPOSE_COMPANION,
    TOKEN_PURPOSE_MCP,
    TOKEN_SCOPES,
    AuthService,
    CompanionCredential,
    PersonalTokenView,
    UserProvisionedHook,
)

__all__ = [
    "ALL_SCOPES",
    "COMPANION_SCOPES",
    "MCP_SCOPES",
    "OPT_IN_SCOPES",
    "TOKEN_PURPOSE_COMPANION",
    "TOKEN_PURPOSE_MCP",
    "TOKEN_SCOPES",
    "AuthService",
    "CompanionCredential",
    "PersonalTokenView",
    "UserProvisionedHook",
]
