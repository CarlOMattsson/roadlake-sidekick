"""The companion adapter and durable push delivery (ntfy)."""

import re
from datetime import time
from typing import Self

from pydantic import Field, SecretStr, field_validator, model_validator

from sidekick.shared.config.base import SettingsGroup

_PUSH_HOST_PATTERN = re.compile(
    r"[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?(\.[a-z0-9]([a-z0-9-]{0,61}[a-z0-9])?)+"
)


def parse_push_allowed_hosts(value: str) -> frozenset[str]:
    """The push endpoint host allowlist: lower-case DNS names with a dot, never an IP literal."""

    hosts = frozenset(item.strip().lower() for item in value.split(",") if item.strip())
    for host in hosts:
        if not _PUSH_HOST_PATTERN.fullmatch(host) or host.replace(".", "").isdigit():
            raise ValueError("SIDEKICK_PUSH_ALLOWED_HOSTS must list plain DNS host names")
    return hosts


class PushSettings(SettingsGroup):
    companion_enabled: bool = Field(
        default=False,
        description="Registers the companion adapter `/companion/v1/` for paired Android devices.",
    )
    push_allowed_hosts: str = Field(
        default="ntfy.sh",
        description="Comma-separated DNS hosts allowed as push endpoints (SSRF guard), never IPs.",
    )
    push_auth_host: str | None = Field(
        default=None,
        description="Self-hosted ntfy host that receives the bearer token; must be allowed above.",
    )
    push_auth_token: SecretStr | None = Field(
        default=None,
        description="Bearer token sent only to the push auth host; unset sends no credentials.",
    )
    push_enabled: bool = Field(
        default=False,
        description="Turns on durable push delivery and the push worker (`sidekick-push-worker`).",
    )
    push_poll_seconds: int = Field(
        default=5,
        ge=1,
        le=300,
        description="Seconds between the push worker's looks at the outbox.",
    )
    push_wake_min_interval_seconds: int = Field(
        default=20,
        ge=0,
        le=3600,
        description="Minimum seconds between wake pushes to one subscription (0 = off).",
    )
    push_summary_time: time = Field(
        default=time(8, 0),
        description="Local time of the morning summary of tasks due today or overdue.",
    )
    push_due_lead_minutes: int = Field(
        default=15,
        ge=0,
        le=720,
        description="Minutes before a task's clock time that its reminder is announced.",
    )
    push_quiet_start: time = Field(
        default=time(21, 0), description="Local time the push quiet hours start."
    )
    push_quiet_end: time = Field(
        default=time(7, 0), description="Local time the push quiet hours end."
    )

    @model_validator(mode="after")
    def validate_push_hosts(self) -> Self:
        if not parse_push_allowed_hosts(self.push_allowed_hosts):
            raise ValueError("SIDEKICK_PUSH_ALLOWED_HOSTS must name at least one host")
        return self

    @field_validator("push_auth_host", "push_auth_token", mode="before")
    @classmethod
    def blank_push_auth_is_unset(cls, value: object) -> object:
        """An empty variable (as a Compose file passes it) means "not configured"."""

        return None if isinstance(value, str) and not value.strip() else value

    @model_validator(mode="after")
    def validate_push_auth(self) -> Self:
        """The message never repeats the token."""

        host = self.push_auth_host.strip().lower() if self.push_auth_host else None
        self.push_auth_host = host
        if self.push_auth_token is None:
            return self
        token = self.push_auth_token.get_secret_value()
        if host is None:
            raise ValueError("SIDEKICK_PUSH_AUTH_TOKEN needs SIDEKICK_PUSH_AUTH_HOST")
        if any(ch.isspace() or not ch.isprintable() for ch in token):
            raise ValueError("SIDEKICK_PUSH_AUTH_TOKEN must not contain whitespace or line breaks")
        if host not in parse_push_allowed_hosts(self.push_allowed_hosts):
            raise ValueError("SIDEKICK_PUSH_AUTH_HOST must be one of SIDEKICK_PUSH_ALLOWED_HOSTS")
        return self

    @model_validator(mode="after")
    def validate_push_reminder_times(self) -> Self:
        start, end, summary = self.push_quiet_start, self.push_quiet_end, self.push_summary_time
        quiet = (summary >= start or summary < end) if start > end else (start <= summary < end)
        if start != end and quiet:
            raise ValueError("SIDEKICK_PUSH_SUMMARY_TIME must lie outside the push quiet hours")
        return self

    @property
    def push_allowed_host_set(self) -> frozenset[str]:
        return parse_push_allowed_hosts(self.push_allowed_hosts)
