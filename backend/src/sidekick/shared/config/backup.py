"""Scheduled encrypted database backups."""

from pathlib import Path
from typing import Self

from pydantic import Field, SecretStr, model_validator

from sidekick.shared.config.base import SettingsGroup


class BackupSettings(SettingsGroup):
    backup_enabled: bool = Field(
        default=False,
        description="Turns on scheduled encrypted database backups; needs a key and a directory.",
    )
    backup_directory: Path = Field(
        default=Path(".sidekick/backups"),
        description="Directory that holds the backups; must be absolute when backups are enabled.",
    )
    backup_encryption_key: SecretStr | None = Field(
        default=None, description="Key that encrypts backups; required when backups are enabled."
    )
    backup_retention_count: int = Field(
        default=30, ge=1, le=3650, description="Most finished backups kept before older ones go."
    )
    backup_retention_days: int = Field(
        default=30, ge=1, le=3650, description="Days a finished backup is kept before it is pruned."
    )
    backup_min_keep: int = Field(
        default=5,
        ge=1,
        le=3650,
        description="Newest finished backups that are never pruned, however old.",
    )
    backup_space_margin_pct: int = Field(
        default=150,
        ge=100,
        le=1000,
        description="Percent of the newest backup's size that must be free before a backup starts.",
    )
    backup_interval_seconds: int = Field(
        default=86_400,
        ge=3_600,
        le=604_800,
        description="Seconds between scheduled backups.",
    )

    @model_validator(mode="after")
    def validate_backup(self) -> Self:
        if self.backup_enabled and (
            self.backup_encryption_key is None
            or not self.backup_encryption_key.get_secret_value().strip()
        ):
            raise ValueError("SIDEKICK_BACKUP_ENCRYPTION_KEY is required when backups are enabled")
        if self.backup_enabled and not self.backup_directory.is_absolute():
            raise ValueError("SIDEKICK_BACKUP_DIRECTORY must be absolute when backups are enabled")
        return self
