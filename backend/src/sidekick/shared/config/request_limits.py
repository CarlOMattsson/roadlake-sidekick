"""Protection of the public surface against slow and failing clients."""

from pydantic import Field

from sidekick.shared.config.base import SettingsGroup


class RequestLimitSettings(SettingsGroup):
    body_read_timeout_seconds: float = Field(
        default=30.0,
        gt=0,
        le=300,
        description="Seconds a public request body may take to arrive; slower gets 408.",
    )
    oauth_body_read_timeout_seconds: float = Field(
        default=10.0,
        gt=0,
        le=300,
        description="Seconds an OAuth form body may take to arrive; slower gets 408.",
    )
    max_buffered_requests: int = Field(
        default=32,
        ge=1,
        le=1024,
        description="Most request bodies (up to 1 MiB each) arriving at once; more gets 503.",
    )
    failed_auth_per_client_per_minute: int = Field(
        default=10,
        ge=1,
        le=10_000,
        description="Failed bearer attempts per minute from one address before further 429s.",
    )
    failed_auth_global_per_minute: int = Field(
        default=60,
        ge=1,
        le=100_000,
        description="Failed bearer attempts per minute from all clients before further 429s.",
    )
    failed_auth_reserve_per_minute: int = Field(
        default=5,
        ge=0,
        le=1_000,
        description="Unknown-token requests per minute that always get through (0 = no reserve).",
    )
