"""When visible reminders are due (ADR-005; D-078, push through UnifiedPush). Pure: no database, no
framework, no clock.

All times are the owner's wall-clock times in `SIDEKICK_OWNER_TIMEZONE` (D-063), the zone the agenda
counts "today" in.

- The morning summary is due from `summary_time` on the owner's day, for `SUMMARY_WINDOW`, and never
  inside the quiet hours.
- A Task has a clock time in `due_at` unless it is 23:59 in the owner's zone: that is how a bare
  date is stored (`end_of_day_due_at`, MCP and the apps), so it carries no time of day to announce.
  A due reminder is due `due_lead` before `due_at`. Inside the quiet hours it is moved to the end of
  them (07:00), the same morning or the next one. It stays eligible for `DUE_WINDOW` after that
  moment, so a worker that was down for a while still announces it, while a `due_at` moved into the
  past is not announced late. Two more rules keep a reminder from announcing something already
  over: one that quiet hours did not move is created only while `now < due_at` (a Task created
  at 10:30 with `due_at` 09:00 gets none); one that quiet hours moved to 07:00 is created only for
  a Task that existed by then (`created_at <= 07:00`), since a Task created after 07:00 with a
  `due_at` during the night is already overdue and shows in the morning summary.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, tzinfo

SUMMARY_WINDOW = timedelta(hours=2)
DUE_WINDOW = timedelta(hours=6)
# A bare date is stored as the last minute of its day.
DATE_ONLY_TIME = time(23, 59)


@dataclass(frozen=True, slots=True)
class ReminderPolicy:
    zone: tzinfo
    summary_time: time
    due_lead: timedelta
    quiet_start: time
    quiet_end: time

    def in_quiet_hours(self, instant: datetime) -> bool:
        local = instant.astimezone(self.zone).time()
        start, end = self.quiet_start, self.quiet_end
        if start == end:
            return False
        if start > end:  # The quiet hours wrap midnight (21:00-07:00).
            return local >= start or local < end
        return start <= local < end

    def summary_day(self, now: datetime) -> date | None:
        """The owner's day whose summary may be queued now, or `None`."""

        local = now.astimezone(self.zone)
        opens = datetime.combine(local.date(), self.summary_time, tzinfo=self.zone)
        if not opens <= local < opens + SUMMARY_WINDOW or self.in_quiet_hours(now):
            return None
        return local.date()

    def has_clock_time(self, due_at: datetime) -> bool:
        local = due_at.astimezone(self.zone)
        return (local.hour, local.minute) != (DATE_ONLY_TIME.hour, DATE_ONLY_TIME.minute)

    def due_reminder_time(self, due_at: datetime) -> datetime | None:
        """When the reminder for a Task due at `due_at` is shown, or `None` for a bare date."""

        if not self.has_clock_time(due_at):
            return None
        moment = due_at - self.due_lead
        if not self.in_quiet_hours(moment):
            return moment
        local = moment.astimezone(self.zone)
        end = datetime.combine(local.date(), self.quiet_end, tzinfo=self.zone)
        if end <= local:
            end = datetime.combine(
                local.date() + timedelta(days=1), self.quiet_end, tzinfo=self.zone
            )
        return end

    def due_reminder_is_due(self, due_at: datetime, now: datetime, created_at: datetime) -> bool:
        """Whether the reminder for a Task created at `created_at` and due at `due_at` may be
        created now."""

        moment = self.due_reminder_time(due_at)
        if moment is None or not moment <= now < moment + DUE_WINDOW:
            return False
        if moment != due_at - self.due_lead:  # Moved to the end of the quiet hours.
            return created_at <= moment
        return now < due_at
