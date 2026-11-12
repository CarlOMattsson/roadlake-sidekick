"""Validated runtime configuration.

`Settings` is the one list of `SIDEKICK_*` environment variables; its groups live in the modules
of this package. Import from `sidekick.shared.config`, not from the group modules.
"""

from functools import lru_cache

from sidekick.shared.config.instance import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.config.oauth import (
    DEFAULT_MCP_OAUTH_REDIRECT_URIS,
    parse_mcp_oauth_identities,
    parse_mcp_oauth_redirect_uris,
    parse_mcp_oauth_scopes,
)
from sidekick.shared.config.push import parse_push_allowed_hosts
from sidekick.shared.config.settings import Settings
from sidekick.shared.config.sources import (
    ConfigurationSources,
    configuration_sources,
    declared_variable_names,
    describe_configuration_sources,
    dotenv_variables,
)
from sidekick.shared.config.validation import PLACEHOLDER_PREFIXES

__all__ = [
    "DEFAULT_MCP_OAUTH_REDIRECT_URIS",
    "DEFAULT_OWNER_TIMEZONE",
    "PLACEHOLDER_PREFIXES",
    "ConfigurationSources",
    "Settings",
    "configuration_sources",
    "declared_variable_names",
    "describe_configuration_sources",
    "dotenv_variables",
    "get_admin_settings",
    "get_settings",
    "parse_mcp_oauth_identities",
    "parse_mcp_oauth_redirect_uris",
    "parse_mcp_oauth_scopes",
    "parse_owner_timezone",
    "parse_push_allowed_hosts",
]


@lru_cache
def get_settings() -> Settings:
    return Settings()  # type: ignore[call-arg]


def get_admin_settings() -> Settings:
    """Settings for the operator CLIs (`sidekick-admin`), which never serve MCP.

    The public OAuth policy is validated only when the server would expose it, and it needs the
    owner's user UUID, which `sidekick-admin create-user` is what prints. Reading the settings in
    `pat` mode breaks that circle. Everything else is still validated, including the production
    secrets, and the OAuth variables are still read and typed; they are just not required to be
    complete. Not cached: a CLI process runs once.
    """

    return Settings(mcp_auth_mode="pat")  # type: ignore[call-arg]
