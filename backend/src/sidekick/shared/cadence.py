"""Declared recurrence rhythm shared by Work and Tasks."""

from datetime import timedelta
from enum import StrEnum

from sidekick.shared.errors import ValidationError


class Cadence(StrEnum):
    """Declared rhythm, shared by Domain review, Process run, and Task blocked-reminder cadence."""

    DAILY = "daily"
    WEEKLY = "weekly"
    BIWEEKLY = "biweekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    YEARLY = "yearly"

    @property
    def interval(self) -> timedelta:
        """Fixed documented interval, so derivation needs no calendar library."""

        return timedelta(days=_CADENCE_DAYS[self])


_CADENCE_DAYS: dict[Cadence, int] = {
    Cadence.DAILY: 1,
    Cadence.WEEKLY: 7,
    Cadence.BIWEEKLY: 14,
    Cadence.MONTHLY: 30,
    Cadence.QUARTERLY: 90,
    Cadence.YEARLY: 365,
}


def parse_cadence(value: str | Cadence | None) -> Cadence | None:
    if value is None or isinstance(value, Cadence):
        return value
    try:
        return Cadence(value)
    except ValueError as error:
        raise ValidationError("unsupported cadence value") from error
