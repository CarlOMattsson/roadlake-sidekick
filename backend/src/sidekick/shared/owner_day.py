"""Where the owner's calendar day and month begin, in the owner's time zone."""

from datetime import datetime, tzinfo


def day_start(now: datetime, zone: tzinfo) -> datetime:
    """The start of the day containing `now` in the owner's time zone."""

    return now.astimezone(zone).replace(hour=0, minute=0, second=0, microsecond=0)


def month_start(now: datetime, zone: tzinfo) -> datetime:
    """The start of the calendar month containing `now` in the owner's time zone."""

    return day_start(now, zone).replace(day=1)
