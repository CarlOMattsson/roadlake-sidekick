"""The owner's instance: time zone, rooms, update reminder and build information."""

from zoneinfo import ZoneInfo

from pydantic import Field, field_validator

from sidekick.shared.build_info import UpdateReminder, update_reminder
from sidekick.shared.config.base import SettingsGroup
from sidekick.shared.rooms import DEFAULT_ENABLED_ROOMS, Room, parse_enabled_rooms

# The owner's own zone: "today" for the agenda and the journal is counted in it.
DEFAULT_OWNER_TIMEZONE = "Europe/Stockholm"


def parse_owner_timezone(value: str) -> ZoneInfo:
    """Return the owner's IANA zone. The message never repeats the value."""

    try:
        return ZoneInfo(value)
    except (KeyError, ValueError, OSError):
        raise ValueError(
            "SIDEKICK_OWNER_TIMEZONE must be an IANA time zone name, for example Europe/Stockholm"
        ) from None


class InstanceSettings(SettingsGroup):
    owner_timezone: str = Field(
        default=DEFAULT_OWNER_TIMEZONE,
        description="IANA time zone of the owner; the agenda's and journal's days count in it.",
    )
    enabled_rooms: str = Field(
        default=DEFAULT_ENABLED_ROOMS,
        description="Comma-separated rooms shown: work, journal, shopping, contacts, control.",
    )
    update_reminder_days: int = Field(
        default=14,
        ge=0,
        le=3650,
        description="Days after which a calm update note shows, judged by code age (0 = off).",
    )
    build_info_file: str = Field(
        default="",
        description="Path of the build-info JSON that tells the age of the running code.",
    )
    build_commit: str = Field(
        default="", description="Commit the running code was built from (baked in by Docker)."
    )
    build_date: str = Field(
        default="", description="ISO 8601 build time with timezone (baked in by Docker)."
    )

    @field_validator("owner_timezone")
    @classmethod
    def validate_owner_timezone(cls, value: str) -> str:
        parse_owner_timezone(value)
        return value

    @field_validator("enabled_rooms")
    @classmethod
    def validate_enabled_rooms(cls, value: str) -> str:
        parse_enabled_rooms(value)
        return value

    @property
    def enabled_room_set(self) -> frozenset[Room]:
        return parse_enabled_rooms(self.enabled_rooms)

    @property
    def update_reminder(self) -> UpdateReminder | None:
        return update_reminder(
            self.update_reminder_days, self.build_info_file, self.build_commit, self.build_date
        )

    @property
    def owner_zone(self) -> ZoneInfo:
        return parse_owner_timezone(self.owner_timezone)
