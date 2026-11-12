"""The public MCP server: its name, language and authentication mode."""

from typing import Literal
from uuid import UUID

from pydantic import Field, ValidationInfo, field_validator

from sidekick.shared.config.base import SettingsGroup
from sidekick.shared.locale import AppLocale


class McpServerSettings(SettingsGroup):
    mcp_server_name: str = Field(
        default="Sidekick",
        description="Name the public MCP server reports; Claude shows it as the connector name.",
    )
    mcp_app_locale: AppLocale = Field(
        default="sv", description="Language of the Sidekick MCP Apps: sv (default) or en."
    )
    mcp_stdio_owner_id: str = Field(
        default="",
        description="User UUID the local stdio entrance acts as; empty means it will not start.",
    )
    mcp_auth_mode: Literal["pat", "github_oauth"] = Field(
        default="pat",
        description="Public MCP authentication: personal access token, or GitHub OAuth sign-in.",
    )
    mcp_public_base_url: str = Field(
        default="",
        description="Bare public origin (HTTPS) the outside world reaches this process on.",
    )

    @field_validator("mcp_stdio_owner_id")
    @classmethod
    def validate_mcp_owner_id(cls, value: str, info: ValidationInfo) -> str:
        text = value.strip()
        if text:
            try:
                UUID(text)
            except ValueError:
                name = f"SIDEKICK_{(info.field_name or '').upper()}"
                raise ValueError(f"{name} must be a user UUID") from None
        return text
