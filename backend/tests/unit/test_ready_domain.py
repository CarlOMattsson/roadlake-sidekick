"""The rules of ready conversations, with no framework and no database.

A conversation is ready on a day its cadence names, from its local time to the end of that day,
unless that day was skipped or started. The cadence is read from the day the conversation was
created, and agrees with the recurrence rule the tasks use for every rule that names its day.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from uuid import uuid4
from zoneinfo import ZoneInfo

import pytest

from sidekick.automations.domain.spec import Cadence
from sidekick.shared.errors import ConflictError, ValidationError
from sidekick.shared.types import UNSET
from sidekick.start.domain.ready import (
    INGREDIENT_SCOPES,
    MAX_INSTRUCTION_CHARS,
    MAX_OUTPUT_BYTES,
    MAX_TITLE_CHARS,
    SKIP_HORIZON_DAYS,
    DayState,
    Ingredient,
    ReadyBlock,
    ReadyChange,
    ReadyConversation,
    ReadyDay,
    ReadyEvent,
    ReadyKind,
    ReadyState,
    change,
    create,
    fit_blocks,
    instruction_verified,
    is_ready,
    normalise_ingredients,
    occurs_on,
    one_line,
    readable_ingredients,
    skip_day,
    start_day,
)

ZONE = ZoneInfo("Europe/Stockholm")
OWNER = uuid4()
NOW = datetime(2026, 11, 23, 19, 0, tzinfo=ZONE)
MONDAY = date(2026, 11, 23)


def _cadence(frequency: str = "daily", local_time: str = "18:00", **rule: object) -> Cadence:
    return Cadence(frequency=frequency, local_time=local_time, **rule)  # type: ignore[arg-type]


def _conversation(cadence: Cadence | None = None, **fields: object) -> ReadyConversation:
    values: dict[str, object] = {
        "id": uuid4(),
        "owner_id": OWNER,
        "title": "Evening review",
        "kind": ReadyKind.EVENING_REVIEW,
        "instruction": "Go through the day with me.",
        "instruction_written_by": "you",
        "instruction_edited_by_model": False,
        "ingredients": (Ingredient.OVERDUE,),
        "cadence": cadence or _cadence(),
        "state": ReadyState.ACTIVE,
        "version": 1,
        "created_at": NOW,
        "updated_at": NOW,
        **fields,
    }
    return ReadyConversation(**values)  # type: ignore[arg-type]


def _days(start: date, count: int) -> list[date]:
    return [start + timedelta(days=offset) for offset in range(count)]


# --- which days a cadence names ---------------------------------------------------------------


def test_a_daily_cadence_names_every_interval_th_day_from_the_anchor() -> None:
    every_third = _cadence(interval=3)

    named = [day for day in _days(MONDAY, 10) if occurs_on(every_third, day, MONDAY)]

    assert named == [
        MONDAY,
        MONDAY + timedelta(days=3),
        MONDAY + timedelta(days=6),
        MONDAY + timedelta(days=9),
    ]


def test_no_cadence_names_a_day_before_its_anchor_or_after_its_end() -> None:
    cadence = _cadence(until=date(2026, 11, 25))

    assert not occurs_on(cadence, MONDAY - timedelta(days=1), MONDAY)
    assert occurs_on(cadence, date(2026, 11, 25), MONDAY)
    assert not occurs_on(cadence, date(2026, 11, 26), MONDAY)


def test_a_weekly_cadence_names_its_weekdays_and_every_interval_th_week() -> None:
    # Monday and Thursday, every second week, counting from the week of the anchor.
    cadence = _cadence("weekly", weekdays=(0, 3), interval=2)

    named = [day for day in _days(MONDAY, 29) if occurs_on(cadence, day, MONDAY)]

    assert named == [
        date(2026, 11, 23),
        date(2026, 11, 26),
        date(2026, 12, 7),
        date(2026, 12, 10),
        date(2026, 12, 21),
    ]


def test_a_weekly_cadence_without_weekdays_keeps_the_weekday_of_its_anchor() -> None:
    cadence = _cadence("weekly")

    assert [day for day in _days(MONDAY, 15) if occurs_on(cadence, day, MONDAY)] == [
        MONDAY,
        MONDAY + timedelta(days=7),
        MONDAY + timedelta(days=14),
    ]


def test_a_monthly_cadence_without_a_day_keeps_the_anchor_day_and_does_not_drift() -> None:
    cadence = _cadence("monthly")
    anchor = date(2026, 1, 31)

    named = [day for day in _days(anchor, 130) if occurs_on(cadence, day, anchor)]

    # A month without the 31st falls on its last day, and March is the 31st again.
    assert named == [
        date(2026, 1, 31),
        date(2026, 2, 28),
        date(2026, 3, 31),
        date(2026, 4, 30),
        date(2026, 5, 31),
    ]


def test_a_monthly_cadence_can_name_the_last_weekday_of_the_month() -> None:
    cadence = _cadence("monthly", last_weekday=True)

    named = [
        day for day in _days(date(2026, 10, 1), 92) if occurs_on(cadence, day, date(2026, 10, 1))
    ]

    # 31 October 2026 is a Saturday, 30 November a Monday, 31 December a Thursday.
    assert named == [date(2026, 10, 30), date(2026, 11, 30), date(2026, 12, 31)]


def test_a_yearly_cadence_falls_on_the_28th_of_february_in_a_common_year() -> None:
    cadence = _cadence("yearly")
    anchor = date(2028, 2, 29)

    assert occurs_on(cadence, date(2029, 2, 28), anchor)
    assert occurs_on(cadence, date(2032, 2, 29), anchor)
    assert not occurs_on(cadence, date(2029, 3, 1), anchor)


@pytest.mark.parametrize(
    "rule",
    [
        {"frequency": "daily", "interval": 2},
        {"frequency": "weekly"},
        {"frequency": "weekly", "weekdays": (1, 4)},
        {"frequency": "weekly", "weekdays": (0, 2, 6), "interval": 2},
        {"frequency": "monthly", "day_of_month": 31},
        {"frequency": "monthly", "last_weekday": True, "interval": 2},
        {"frequency": "yearly"},
    ],
)
def test_it_names_the_days_the_task_recurrence_names(rule: dict[str, object]) -> None:
    """For every rule that names its day, the days are the ones `RecurrenceRule` steps through."""

    cadence = _cadence(**rule)
    anchor = datetime(2026, 11, 23, 18, 0, tzinfo=ZONE)
    stepped: set[date] = set()
    occurrence: datetime | None = anchor
    # `next_due_at` skips the anchor day itself, which `occurs_on` counts when the rule names it.
    while occurrence is not None and occurrence.astimezone(ZONE).date() < date(2028, 12, 31):
        occurrence = cadence.rule().next_due_at(occurrence, ZONE)
        if occurrence is not None:
            stepped.add(occurrence.astimezone(ZONE).date())

    horizon = anchor.date() + timedelta(days=730)
    named = {
        day
        for day in _days(anchor.date() + timedelta(days=1), 730)
        if occurs_on(cadence, day, anchor.date())
    }
    if cadence.frequency == "monthly":
        # A monthly occurrence of `next_due_at` is always in a later month than the one it starts
        # from; a conversation created early in a month may be ready later in that same month.
        named = {day for day in named if (day.year, day.month) != (anchor.year, anchor.month)}

    assert named == {day for day in stepped if day <= horizon}


# --- the ready window -------------------------------------------------------------------------


def _ready(conversation: ReadyConversation, local: time, state: DayState | None = None) -> bool:
    return is_ready(conversation, anchor=MONDAY, today=MONDAY, local_now=local, day_state=state)


def test_a_conversation_is_ready_from_its_time_to_the_end_of_a_cadence_day() -> None:
    conversation = _conversation(_cadence(local_time="18:00"))

    assert not _ready(conversation, time(17, 59))
    assert _ready(conversation, time(18, 0))
    assert _ready(conversation, time(23, 59, 59))


def test_a_skipped_or_started_day_is_not_ready_but_a_reopened_one_is() -> None:
    conversation = _conversation()

    assert not _ready(conversation, time(19, 0), DayState.SKIPPED)
    assert not _ready(conversation, time(19, 0), DayState.STARTED)
    assert _ready(conversation, time(19, 0), DayState.OPEN)


def test_a_paused_or_archived_conversation_is_never_ready() -> None:
    for state in (ReadyState.PAUSED, ReadyState.ARCHIVED):
        assert not _ready(_conversation(state=state), time(19, 0))


def test_a_day_the_cadence_does_not_name_is_not_ready() -> None:
    conversation = _conversation(_cadence("weekly", weekdays=(2,)))  # Wednesdays only

    assert not _ready(conversation, time(19, 0))


# --- skip and start --------------------------------------------------------------------------


def test_skipping_a_day_and_undoing_it_moves_one_row_and_never_the_schedule() -> None:
    conversation = _conversation()
    kwargs = {"today": MONDAY, "anchor": MONDAY, "now": NOW}

    skipped = skip_day(conversation, None, MONDAY, undo=False, **kwargs)
    assert skipped is not None and (skipped.state, skipped.version) == (DayState.SKIPPED, 1)
    # Skipping again changes nothing.
    assert skip_day(conversation, skipped, MONDAY, undo=False, **kwargs) is skipped

    reopened = skip_day(conversation, skipped, MONDAY, undo=True, **kwargs)
    assert reopened is not None and (reopened.state, reopened.version) == (DayState.OPEN, 2)
    # Undoing what is not skipped changes nothing, and neither does it for a day with no row.
    assert skip_day(conversation, reopened, MONDAY, undo=True, **kwargs) is reopened
    assert skip_day(conversation, None, MONDAY, undo=True, **kwargs) is None


def test_a_started_day_cannot_be_skipped() -> None:
    conversation = _conversation()
    started = ReadyDay(conversation.id, MONDAY, DayState.STARTED, NOW, 1)

    with pytest.raises(ConflictError):
        skip_day(conversation, started, MONDAY, undo=False, today=MONDAY, anchor=MONDAY, now=NOW)


def test_only_a_day_from_today_within_the_horizon_that_the_cadence_names_can_be_skipped() -> None:
    conversation = _conversation(_cadence("weekly", weekdays=(0,)))
    kwargs = {"undo": False, "today": MONDAY, "anchor": MONDAY, "now": NOW}

    for refused in (
        MONDAY - timedelta(days=7),
        MONDAY + timedelta(days=SKIP_HORIZON_DAYS + 7),
        MONDAY + timedelta(days=1),  # a Tuesday, which the cadence does not name
    ):
        with pytest.raises(ValidationError):
            skip_day(conversation, None, refused, **kwargs)
    assert skip_day(conversation, None, MONDAY + timedelta(days=28), **kwargs) is not None


def test_only_an_active_conversation_can_be_skipped_or_started() -> None:
    paused = _conversation(state=ReadyState.PAUSED)

    with pytest.raises(ValidationError):
        skip_day(paused, None, MONDAY, undo=False, today=MONDAY, anchor=MONDAY, now=NOW)
    with pytest.raises(ValidationError):
        start_day(paused, None, MONDAY, now=NOW)


def test_starting_a_day_twice_is_one_start_and_a_skipped_day_can_be_started() -> None:
    conversation = _conversation()
    skipped = ReadyDay(conversation.id, MONDAY, DayState.SKIPPED, NOW, 3)

    started = start_day(conversation, skipped, MONDAY, now=NOW)

    assert (started.state, started.version) == (DayState.STARTED, 4)
    assert start_day(conversation, started, MONDAY, now=NOW) is started


# --- writing a conversation ------------------------------------------------------------------


def test_a_new_conversation_needs_a_title_and_a_cadence_and_is_active() -> None:
    made = create(
        conversation_id=uuid4(),
        owner_id=OWNER,
        title="  Morning ​plan ",
        kind=None,
        instruction=None,
        ingredients=[Ingredient.WAITING, Ingredient.OVERDUE, Ingredient.WAITING],
        cadence=_cadence(),
        now=NOW,
    )

    item = made.conversation
    assert made.events == (ReadyEvent.CREATED,)
    assert (item.title, item.kind, item.state, item.version) == (
        "Morning plan",
        ReadyKind.CUSTOM,
        ReadyState.ACTIVE,
        1,
    )
    # No repeats, and the catalogue's order whatever order the caller used.
    assert item.ingredients == (Ingredient.OVERDUE, Ingredient.WAITING)
    for missing in ({"title": None}, {"cadence": None}):
        values = {
            "conversation_id": uuid4(),
            "owner_id": OWNER,
            "title": "T",
            "kind": None,
            "instruction": None,
            "ingredients": None,
            "cadence": _cadence(),
            "now": NOW,
            **missing,
        }
        with pytest.raises(ValidationError):
            create(**values)  # type: ignore[arg-type]


def test_text_is_cleaned_and_bounded() -> None:
    with pytest.raises(ValidationError):
        create(
            conversation_id=uuid4(),
            owner_id=OWNER,
            title="x" * (MAX_TITLE_CHARS + 1),
            kind=None,
            instruction=None,
            ingredients=None,
            cadence=_cadence(),
            now=NOW,
        )
    changed = change(
        _conversation(),
        ReadyChange(instruction="<script>alert(1)</script>\n  go on  "),
        now=NOW,
    )
    assert "<script" not in (changed.conversation.instruction or "")
    with pytest.raises(ValidationError):
        change(_conversation(), ReadyChange(instruction="y" * (MAX_INSTRUCTION_CHARS + 1)), now=NOW)


def test_a_change_bumps_the_version_and_a_change_that_changes_nothing_does_not() -> None:
    current = _conversation()

    renamed = change(current, ReadyChange(title="Evening look"), now=NOW + timedelta(hours=1))
    assert (renamed.conversation.version, renamed.events) == (2, (ReadyEvent.UPDATED,))
    assert renamed.conversation.updated_at == NOW + timedelta(hours=1)

    same = change(current, ReadyChange(title=current.title, kind=current.kind), now=NOW)
    assert same.conversation is current and same.events == ()


def test_the_instruction_is_emptied_only_when_it_is_sent_as_none() -> None:
    current = _conversation()

    assert change(current, ReadyChange(), now=NOW).conversation.instruction == current.instruction
    assert (
        change(current, ReadyChange(instruction=UNSET), now=NOW).conversation.instruction
        == current.instruction
    )
    assert change(current, ReadyChange(instruction=None), now=NOW).conversation.instruction is None


def test_pause_resume_archive_and_restore_move_the_state_and_an_archive_needs_a_restore() -> None:
    active = _conversation()

    paused = change(active, ReadyChange(paused=True), now=NOW)
    assert (paused.conversation.state, paused.events) == (ReadyState.PAUSED, (ReadyEvent.PAUSED,))
    resumed = change(paused.conversation, ReadyChange(paused=False), now=NOW)
    assert resumed.conversation.state is ReadyState.ACTIVE
    archived = change(resumed.conversation, ReadyChange(archived=True), now=NOW)
    assert archived.conversation.state is ReadyState.ARCHIVED
    with pytest.raises(ValidationError):
        change(archived.conversation, ReadyChange(title="New"), now=NOW)
    restored = change(archived.conversation, ReadyChange(archived=False), now=NOW)
    # Restoring brings it back paused: the owner resumes it.
    assert (restored.conversation.state, restored.events) == (
        ReadyState.PAUSED,
        (ReadyEvent.RESTORED,),
    )
    assert change(
        restored.conversation, ReadyChange(archived=True, paused=False), now=NOW
    ).events == (ReadyEvent.ARCHIVED,)


# --- what a start reads ----------------------------------------------------------------------


def test_an_ingredient_is_read_only_with_every_scope_it_needs() -> None:
    wanted = tuple(Ingredient)

    assert readable_ingredients(wanted, frozenset()) == ()
    assert readable_ingredients(wanted, frozenset({"tasks:read"})) == (
        Ingredient.TASKS_DUE_TODAY,
        Ingredient.TASKS_DUE_TOMORROW,
        Ingredient.OVERDUE,
        Ingredient.WAITING,
    )
    # The done list of a day is read with the Journal day, so it needs both scopes.
    assert Ingredient.TASKS_DONE_TODAY in readable_ingredients(
        wanted, frozenset({"tasks:read", "journal:read"})
    )
    assert set(INGREDIENT_SCOPES) == set(Ingredient)
    assert normalise_ingredients(reversed(wanted)) == wanted


def test_one_line_text_is_clean_and_cut_to_the_limit() -> None:
    assert one_line("a​  b\n c") == "a b c"
    cut = one_line("w" * 500, 20)
    assert len(cut) == 20 and cut.endswith("…")
    assert "<" not in one_line("<img src=x onerror=alert(1)>")[:1]


def test_the_blocks_are_cut_line_by_line_from_the_longest_until_they_fit() -> None:
    def block(ingredient: Ingredient, lines: int) -> ReadyBlock:
        return ReadyBlock(ingredient, count=lines, lines=tuple("x" * 140 for _ in range(lines)))

    blocks = [
        block(Ingredient.OVERDUE, 5),
        block(Ingredient.WAITING, 5),
        block(Ingredient.SUGGESTIONS, 0),
    ]

    unchanged, cut = fit_blocks(blocks, MAX_OUTPUT_BYTES)
    assert unchanged == tuple(blocks) and not cut

    fitted, cut = fit_blocks(blocks, 900)
    assert cut
    assert [item.count for item in fitted] == [5, 5, 0], "counts are never cut"
    assert sum(len(item.lines) for item in fitted) < 10
    assert all(item.truncated for item in fitted if len(item.lines) < item.count)
    # The longest loses a line first, so neither is emptied while the other still holds five.
    assert abs(len(fitted[0].lines) - len(fitted[1].lines)) <= 1


# --- who wrote the instruction ---------------------------------------------------------------


def _created(instruction: str | None, source: str | None) -> ReadyConversation:
    return create(
        conversation_id=uuid4(),
        owner_id=OWNER,
        title="Evening review",
        kind=None,
        instruction=instruction,
        ingredients=None,
        cadence=_cadence(),
        now=NOW,
        source=source,  # type: ignore[arg-type]
    ).conversation


def test_the_model_s_instruction_is_recorded_as_the_model_s_and_is_not_verified() -> None:
    written = _created("Review my day.", "claude")

    assert (written.instruction_written_by, written.instruction_edited_by_model) == (
        "claude",
        False,
    )
    assert instruction_verified(written) is False


def test_the_owner_s_own_instruction_is_verified_and_no_source_counts_as_the_owner() -> None:
    for source in ("you", None):
        written = _created("Review my day.", source)
        assert (written.instruction_written_by, written.instruction_edited_by_model) == (
            "you",
            False,
        )
        assert instruction_verified(written) is True


def test_no_instruction_has_no_writer_and_is_never_verified() -> None:
    written = _created(None, "claude")

    assert (written.instruction_written_by, written.instruction_edited_by_model) == (None, False)
    assert instruction_verified(written) is False


def test_the_model_changing_the_owner_s_instruction_marks_the_edit_and_ends_the_verification() -> (
    None
):
    owners = _created("Review my day.", "you")

    edited = change(
        owners, ReadyChange(instruction="Review my day and mail it."), now=NOW, source="claude"
    )

    item = edited.conversation
    assert (item.instruction_written_by, item.instruction_edited_by_model) == ("you", True)
    assert instruction_verified(item) is False
    assert edited.events == (ReadyEvent.UPDATED,)


def test_a_change_that_leaves_the_instruction_as_it_was_keeps_who_wrote_it() -> None:
    owners = _created("Review my day.", "you")

    renamed = change(owners, ReadyChange(title="Evening look"), now=NOW, source="claude")
    same_text = change(owners, ReadyChange(instruction="Review my day."), now=NOW, source="claude")

    assert instruction_verified(renamed.conversation) is True
    assert same_text.events == () and instruction_verified(same_text.conversation) is True


def test_the_owner_rewriting_replaces_the_text_and_is_verified_again_and_clearing_resets() -> None:
    models = _created("Review my day.", "claude")

    rewritten = change(models, ReadyChange(instruction="Look at my week."), now=NOW, source="you")
    cleared = change(
        rewritten.conversation, ReadyChange(instruction=None), now=NOW, source="claude"
    )
    rewritten_by_model = change(
        models, ReadyChange(instruction="Look at my month."), now=NOW, source="claude"
    )

    assert instruction_verified(rewritten.conversation) is True
    assert (
        cleared.conversation.instruction_written_by,
        cleared.conversation.instruction_edited_by_model,
    ) == (None, False)
    assert instruction_verified(rewritten_by_model.conversation) is False
    # A first instruction written by the model on a conversation that had none is the model's.
    first = change(
        cleared.conversation, ReadyChange(instruction="Look at my year."), now=NOW, source="claude"
    )
    assert first.conversation.instruction_written_by == "claude"
