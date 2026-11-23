"""Ready conversations: the rules of a schedule, of its days and of what a start reads.

A ready conversation is a standing prompt the owner's Claude can offer on a schedule. It is ready
on a day its cadence names, from its local time until the end of that day (in the owner's zone),
unless that day was skipped or the conversation was already started. These are plain values and
pure functions: nothing here knows storage, a clock or a transport.

The cadence is the one an automation has (`Cadence`: a recurrence rule and a time of day). A rule
that has to say which days it names, with no memory of earlier occurrences, counts from the day the
conversation was created (`anchor`), so an interval of two weeks stays two weeks whatever was
skipped. `occurs_on` is that reading; it names the days `RecurrenceRule.next_due_at` steps through
(a test pins it), and a monthly rule may also name a later day in the anchor's own month, which a
completion never does.
"""

from __future__ import annotations

import calendar
import json
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from enum import StrEnum
from typing import Final
from uuid import UUID

from sidekick.automations.domain.spec import Cadence
from sidekick.automations.domain.text import normalise_block, normalise_line
from sidekick.shared.change_source import ChangeSource
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import UNSET, UnsetType

MAX_TITLE_CHARS: Final = 80
MAX_INSTRUCTION_CHARS: Final = 2000
MAX_OPEN_CONVERSATIONS: Final = 20
"""Active and paused conversations one owner may hold; an archived one does not count."""
DAY_RETENTION_DAYS: Final = 60
"""A day row older than this is deleted when a newer one is written."""
SKIP_HORIZON_DAYS: Final = 31
"""How far ahead a day may be skipped."""
MAX_OUTPUT_BYTES: Final = 8 * 1024
"""What the composed summary of one start may weigh, as JSON."""
BLOCK_LINE_LIMIT: Final = 5
LINE_CHARS: Final = 140


class ReadyKind(StrEnum):
    EVENING_REVIEW = "evening_review"
    MORNING_PLAN = "morning_plan"
    WEEKLY_REVIEW = "weekly_review"
    CUSTOM = "custom"


class Ingredient(StrEnum):
    """What a start may read. The set is closed; each one needs its own read scope."""

    TASKS_DONE_TODAY = "tasks_done_today"
    TASKS_DUE_TODAY = "tasks_due_today"
    TASKS_DUE_TOMORROW = "tasks_due_tomorrow"
    OVERDUE = "overdue"
    WAITING = "waiting"
    SUGGESTIONS = "suggestions"
    JOURNAL_TODAY = "journal_today"
    REVIEW = "review"
    AUTOMATION_REPORT = "automation_report"
    SHOPPING_OPEN = "shopping_open"


INGREDIENT_ORDER: Final[tuple[Ingredient, ...]] = tuple(Ingredient)

INGREDIENT_SCOPES: Final[Mapping[Ingredient, frozenset[str]]] = {
    # The done list of a day is read with the Journal day, so it needs that scope as well.
    Ingredient.TASKS_DONE_TODAY: frozenset({"tasks:read", "journal:read"}),
    # The titles of the Projects the tasks belong to are shown only with `projects:read`.
    Ingredient.TASKS_DUE_TODAY: frozenset({"tasks:read"}),
    Ingredient.TASKS_DUE_TOMORROW: frozenset({"tasks:read"}),
    Ingredient.OVERDUE: frozenset({"tasks:read"}),
    Ingredient.WAITING: frozenset({"tasks:read"}),
    Ingredient.SUGGESTIONS: frozenset({"automation:read"}),
    Ingredient.JOURNAL_TODAY: frozenset({"journal:read"}),
    Ingredient.REVIEW: frozenset({"review:read"}),
    Ingredient.AUTOMATION_REPORT: frozenset({"automation:read"}),
    Ingredient.SHOPPING_OPEN: frozenset({"shopping:read"}),
}
"""The read scopes an ingredient needs. A start leaves out one the caller cannot read, silently."""


class ReadyState(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"
    ARCHIVED = "archived"


class DayState(StrEnum):
    SKIPPED = "skipped"
    STARTED = "started"
    OPEN = "open"
    """A skip that was undone."""


class ReadyEvent(StrEnum):
    """What a write did, one word per audit event."""

    CREATED = "created"
    UPDATED = "updated"
    PAUSED = "paused"
    RESUMED = "resumed"
    ARCHIVED = "archived"
    RESTORED = "restored"


@dataclass(frozen=True, slots=True)
class ReadyConversation:
    id: UUID
    owner_id: UUID
    title: str
    kind: ReadyKind
    instruction: str | None
    """Text for Claude to act on when a start hands it back. It is only as trustworthy as whoever
    wrote it: see `instruction_verified`."""
    instruction_written_by: ChangeSource | None
    """Who first wrote the instruction text: `you` (the owner in the app) or `claude` (through a
    tool). `None` when there is no instruction."""
    instruction_edited_by_model: bool
    """True when the model changed an instruction the owner had written."""
    ingredients: tuple[Ingredient, ...]
    cadence: Cadence
    state: ReadyState
    version: int
    created_at: datetime
    updated_at: datetime


@dataclass(frozen=True, slots=True)
class ReadyDay:
    """What happened to a conversation on one calendar day. Absent means nothing did."""

    conversation_id: UUID
    day: date
    state: DayState
    changed_at: datetime
    version: int


@dataclass(frozen=True, slots=True)
class ReadyChange:
    """What a caller sent. `instruction` is `None` to empty it and `UNSET` to leave it."""

    title: str | None = None
    kind: ReadyKind | None = None
    instruction: str | UnsetType | None = UNSET
    ingredients: Sequence[Ingredient] | None = None
    cadence: Cadence | None = None
    paused: bool | None = None
    archived: bool | None = None


@dataclass(frozen=True, slots=True)
class ReadyResult:
    """The conversation after a write and the events to audit; none means nothing changed."""

    conversation: ReadyConversation
    events: tuple[ReadyEvent, ...]


# --- text ---------------------------------------------------------------------------------------


def normalise_title(value: str) -> str:
    """The title as it is stored: one line, 1 to 80 characters."""

    title = normalise_line(value)
    if not 1 <= len(title) <= MAX_TITLE_CHARS:
        raise ValidationError(f"title must be 1-{MAX_TITLE_CHARS} characters long")
    return title


def normalise_instruction(value: str) -> str:
    """The owner's words for Claude, cleaned of invisible characters and markup."""

    text = normalise_block(value)
    if not 1 <= len(text) <= MAX_INSTRUCTION_CHARS:
        raise ValidationError(f"instruction must be 1-{MAX_INSTRUCTION_CHARS} characters long")
    return text


def normalise_ingredients(values: Iterable[Ingredient]) -> tuple[Ingredient, ...]:
    """The ingredients without repeats, in the catalogue's own order."""

    wanted = set(values)
    return tuple(item for item in INGREDIENT_ORDER if item in wanted)


def instruction_verified(conversation: ReadyConversation) -> bool:
    """True only for an instruction the owner wrote and the model never touched. Anything else may
    carry text the model took from somewhere else, so it is shown as unverified."""

    return (
        conversation.instruction is not None
        and conversation.instruction_written_by == "you"
        and not conversation.instruction_edited_by_model
    )


def _provenance(
    current: ReadyConversation | None, text: str | None, source: ChangeSource | None
) -> tuple[ChangeSource | None, bool]:
    """Who wrote the instruction `text` that replaces `current`'s, and whether the model edited it.

    The owner's own rewrite replaces the text wholesale and is the owner's. The model's first write
    is the model's; the model's change to an owner's text keeps the owner as the writer and marks
    the edit. A text that did not change keeps what it had.
    """

    who: ChangeSource = source or "you"
    if text is None:
        return None, False
    if current is None or current.instruction is None:
        return who, False
    if text == current.instruction:
        return current.instruction_written_by, current.instruction_edited_by_model
    if who == "you":
        return "you", False
    return current.instruction_written_by, True


# --- writes -------------------------------------------------------------------------------------


def create(
    *,
    conversation_id: UUID,
    owner_id: UUID,
    title: str | None,
    kind: ReadyKind | None,
    instruction: str | None,
    ingredients: Sequence[Ingredient] | None,
    cadence: Cadence | None,
    now: datetime,
    source: ChangeSource | None = None,
) -> ReadyResult:
    """A new active conversation. It needs a title and a cadence; the rest has defaults."""

    if title is None:
        raise ValidationError("a new ready conversation needs a title")
    if cadence is None:
        raise ValidationError("a new ready conversation needs a cadence")
    text = None if instruction is None else normalise_instruction(instruction)
    written_by, edited = _provenance(None, text, source)
    conversation = ReadyConversation(
        id=conversation_id,
        owner_id=owner_id,
        title=normalise_title(title),
        kind=kind or ReadyKind.CUSTOM,
        instruction=text,
        instruction_written_by=written_by,
        instruction_edited_by_model=edited,
        ingredients=normalise_ingredients(ingredients or ()),
        cadence=cadence,
        state=ReadyState.ACTIVE,
        version=1,
        created_at=now,
        updated_at=now,
    )
    return ReadyResult(conversation, (ReadyEvent.CREATED,))


def _requested_state(
    state: ReadyState, requested: ReadyChange
) -> tuple[ReadyState, tuple[ReadyEvent, ...]]:
    if requested.archived is True:
        if state is ReadyState.ARCHIVED:
            return state, ()
        return ReadyState.ARCHIVED, (ReadyEvent.ARCHIVED,)
    events: list[ReadyEvent] = []
    if state is ReadyState.ARCHIVED:
        state = ReadyState.PAUSED
        events.append(ReadyEvent.RESTORED)
    if requested.paused is True and state is not ReadyState.PAUSED:
        state = ReadyState.PAUSED
        events.append(ReadyEvent.PAUSED)
    elif requested.paused is False and state is ReadyState.PAUSED:
        state = ReadyState.ACTIVE
        events.append(ReadyEvent.RESUMED)
    return state, tuple(events)


def change(
    current: ReadyConversation,
    requested: ReadyChange,
    *,
    now: datetime,
    source: ChangeSource | None = None,
) -> ReadyResult:
    """The conversation with the change applied, or unchanged (and no events) when nothing changes.

    An archived conversation can only be restored: until then every other change is refused.
    """

    if current.state is ReadyState.ARCHIVED and requested.archived is not False:
        raise ValidationError(
            "an archived ready conversation must be restored before it is changed"
        )
    title = current.title if requested.title is None else normalise_title(requested.title)
    instruction = current.instruction
    if requested.instruction is None:
        instruction = None
    elif not isinstance(requested.instruction, UnsetType):
        instruction = normalise_instruction(requested.instruction)
    written_by, edited_by_model = _provenance(current, instruction, source)
    ingredients = (
        current.ingredients
        if requested.ingredients is None
        else normalise_ingredients(requested.ingredients)
    )
    edited = replace(
        current,
        title=title,
        kind=requested.kind or current.kind,
        instruction=instruction,
        instruction_written_by=written_by,
        instruction_edited_by_model=edited_by_model,
        ingredients=ingredients,
        cadence=requested.cadence or current.cadence,
    )
    events: list[ReadyEvent] = []
    if edited != current:
        events.append(ReadyEvent.UPDATED)
    state, state_events = _requested_state(current.state, requested)
    events.extend(state_events)
    if not events:
        return ReadyResult(current, ())
    return ReadyResult(
        replace(edited, state=state, updated_at=now, version=current.version + 1), tuple(events)
    )


# --- days ---------------------------------------------------------------------------------------


def local_time_of(cadence: Cadence) -> time:
    hour, minute = (int(part) for part in cadence.local_time.split(":"))
    return time(hour, minute)


def _last_day_of_month(year: int, month: int) -> date:
    return date(year, month, calendar.monthrange(year, month)[1])


def _monday(day: date) -> date:
    return day - timedelta(days=day.weekday())


def occurs_on(cadence: Cadence, day: date, anchor: date) -> bool:
    """Whether the cadence names `day`, counting from `anchor` (the day it was created).

    The anchor day counts when the rule names it; a day before the anchor or after `until` never
    does. A monthly rule without a day of its own keeps the anchor's day, and a day the month lacks
    (the 31st in a short month) falls on the month's last day, every month, without drifting.
    """

    rule = cadence.rule()
    if day < anchor or (rule.until is not None and day > rule.until):
        return False
    interval = rule.interval
    if rule.frequency == "daily":
        return (day - anchor).days % interval == 0
    if rule.frequency == "weekly":
        weekdays = rule.weekdays or (anchor.weekday(),)
        weeks = (_monday(day) - _monday(anchor)).days // 7
        return day.weekday() in weekdays and weeks % interval == 0
    if rule.frequency == "monthly":
        months = (day.year - anchor.year) * 12 + day.month - anchor.month
        if months % interval:
            return False
        last = _last_day_of_month(day.year, day.month)
        if rule.last_weekday:
            return day == last - timedelta(days=max(0, last.weekday() - 4))
        return day.day == min(rule.day_of_month or anchor.day, last.day)
    years = day.year - anchor.year
    last = _last_day_of_month(day.year, anchor.month)
    return years % interval == 0 and day == date(day.year, anchor.month, min(anchor.day, last.day))


def is_ready(
    conversation: ReadyConversation,
    *,
    anchor: date,
    today: date,
    local_now: time,
    day_state: DayState | None,
) -> bool:
    """Ready on a cadence day from its local time to the day's end, unless skipped or started."""

    return (
        conversation.state is ReadyState.ACTIVE
        and day_state not in (DayState.SKIPPED, DayState.STARTED)
        and occurs_on(conversation.cadence, today, anchor)
        and local_now >= local_time_of(conversation.cadence)
    )


def skip_day(
    conversation: ReadyConversation,
    current: ReadyDay | None,
    day: date,
    *,
    undo: bool,
    today: date,
    anchor: date,
    now: datetime,
) -> ReadyDay | None:
    """The day row after a skip (or its undo), or `current` when nothing changes.

    Only a day from today to `SKIP_HORIZON_DAYS` ahead that the cadence names can be skipped. A
    started day cannot be skipped (a conversation that began is not unbegun); undoing a skip that
    is not there changes nothing, and an undo does not look at the cadence, which may have changed
    since.
    """

    if not today <= day <= today + timedelta(days=SKIP_HORIZON_DAYS):
        raise ValidationError(f"day must be from today to {SKIP_HORIZON_DAYS} days ahead")
    if conversation.state is not ReadyState.ACTIVE:
        raise ValidationError("only an active ready conversation can be skipped")
    state = current.state if current is not None else None
    if undo:
        if current is None or state is not DayState.SKIPPED:
            return current
        return _next(current, DayState.OPEN, conversation, day, now)
    if not occurs_on(conversation.cadence, day, anchor):
        raise ValidationError("the conversation is not scheduled that day")
    if state is DayState.STARTED:
        raise ConflictError("the conversation was already started that day")
    if state is DayState.SKIPPED:
        return current
    return _next(current, DayState.SKIPPED, conversation, day, now)


def start_day(
    conversation: ReadyConversation, current: ReadyDay | None, day: date, *, now: datetime
) -> ReadyDay:
    """The day row after a start; starting a started day changes nothing."""

    if conversation.state is not ReadyState.ACTIVE:
        raise ValidationError("only an active ready conversation can be started")
    if current is not None and current.state is DayState.STARTED:
        return current
    return _next(current, DayState.STARTED, conversation, day, now)


def _next(
    current: ReadyDay | None,
    state: DayState,
    conversation: ReadyConversation,
    day: date,
    now: datetime,
) -> ReadyDay:
    version = 1 if current is None else current.version + 1
    return ReadyDay(conversation.id, day, state, now, version)


# --- what a start reads -------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class ReadyBlock:
    """What one ingredient found: a count, a few one-line items and any other counts it names."""

    ingredient: Ingredient
    count: int
    lines: tuple[str, ...] = ()
    details: Mapping[str, int] | None = None
    truncated: bool = False
    """True when more items exist than `lines` shows."""


def one_line(value: str, limit: int = LINE_CHARS) -> str:
    """One clean line of owner or third-party text, cut to `limit` characters."""

    line = normalise_line(value)
    return line if len(line) <= limit else line[: limit - 1].rstrip() + "…"


def readable_ingredients(
    ingredients: Iterable[Ingredient], scopes: frozenset[str]
) -> tuple[Ingredient, ...]:
    """The ingredients whose every read scope the caller holds; the rest are dropped."""

    return tuple(item for item in ingredients if INGREDIENT_SCOPES[item] <= scopes)


def _weight(blocks: Sequence[ReadyBlock]) -> int:
    return len(json.dumps(_as_data(blocks), ensure_ascii=False).encode())


def _as_data(blocks: Sequence[ReadyBlock]) -> list[dict[str, object]]:
    return [
        {
            "ingredient": block.ingredient.value,
            "count": block.count,
            "lines": list(block.lines),
            "details": dict(block.details) if block.details else None,
            "truncated": block.truncated,
        }
        for block in blocks
    ]


def fit_blocks(
    blocks: Sequence[ReadyBlock], limit: int = MAX_OUTPUT_BYTES
) -> tuple[tuple[ReadyBlock, ...], bool]:
    """The blocks within `limit` bytes as JSON, and whether any line had to go.

    The longest block loses its last line first, so no ingredient is dropped while another still
    holds five. Counts are kept: only the lines of a block are shortened.
    """

    kept = list(blocks)
    cut = False
    while _weight(kept) > limit:
        longest = max(range(len(kept)), key=lambda index: (len(kept[index].lines), -index))
        if not kept[longest].lines:
            break
        shortened = kept[longest].lines[:-1]
        kept[longest] = replace(kept[longest], lines=shortened, truncated=True)
        cut = True
    return tuple(kept), cut
