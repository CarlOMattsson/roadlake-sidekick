"""The rules of 'levels of knowing': what raises a level, what never lowers it, option order."""

from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.library.domain.errors import LibraryRefusedError
from sidekick.library.domain.levels import (
    Attempt,
    FactDraft,
    Level,
    LevelState,
    QuestionDraft,
    SetKind,
    advance,
    full_set_missing,
    grade_answer,
    option_order,
    reached_level,
    validate_facts,
    validate_question_set,
)

NOW = datetime(2026, 11, 22, 12, 0, tzinfo=UTC)


def ids(count: int) -> list[UUID]:
    return [uuid4() for _ in range(count)]


def right(question_ids: list[UUID]) -> list[Attempt]:
    return [Attempt(question_id, True) for question_id in question_ids]


class TestReachedLevel:
    def test_a_source_without_answers_is_saved(self) -> None:
        assert reached_level(overview=ids(3), full=ids(5), attempts=[]) == Level.SAVED

    def test_three_correct_overview_answers_recognise_it(self) -> None:
        overview = ids(3)

        assert (
            reached_level(overview=overview, full=[], attempts=right(overview)) == Level.RECOGNISED
        )

    def test_two_of_three_is_not_enough(self) -> None:
        overview = ids(3)

        attempts = right(overview[:2])

        assert reached_level(overview=overview, full=[], attempts=attempts) == Level.SAVED

    def test_a_wrong_answer_counts_for_nothing_and_a_later_right_one_counts(self) -> None:
        overview = ids(3)
        wrong = [Attempt(overview[0], False), Attempt(overview[1], False)]

        assert reached_level(
            overview=overview, full=[], attempts=[*wrong, *right(overview[1:])]
        ) == (Level.SAVED)
        assert reached_level(overview=overview, full=[], attempts=[*wrong, *right(overview)]) == (
            Level.RECOGNISED
        )

    def test_the_full_set_makes_it_understood_only_after_recognised(self) -> None:
        overview, full = ids(3), ids(5)

        assert reached_level(overview=overview, full=full, attempts=right(full)) == Level.SAVED
        assert reached_level(overview=overview, full=full, attempts=right(overview)) == (
            Level.RECOGNISED
        )
        assert reached_level(overview=overview, full=full, attempts=right(overview + full)) == (
            Level.UNDERSTOOD
        )

    def test_an_item_without_a_full_set_stops_at_recognised(self) -> None:
        overview = ids(3)

        assert reached_level(overview=overview, full=[], attempts=right(overview)) == (
            Level.RECOGNISED
        )
        assert full_set_missing([])
        assert full_set_missing(ids(4))
        assert full_set_missing(ids(13))
        assert not full_set_missing(ids(5))
        assert not full_set_missing(ids(12))

    @pytest.mark.parametrize("count", [0, 1, 2, 4])
    def test_an_overview_set_that_is_not_three_questions_never_recognises(self, count: int) -> None:
        overview = ids(count)

        assert reached_level(overview=overview, full=[], attempts=right(overview)) == Level.SAVED

    def test_a_full_set_outside_five_to_twelve_never_understands(self) -> None:
        overview = ids(3)
        for size in (1, 4, 13):
            full = ids(size)
            attempts = right(overview + full)
            assert reached_level(overview=overview, full=full, attempts=attempts) == (
                Level.RECOGNISED
            )

    def test_a_repeated_question_id_makes_a_set_invalid(self) -> None:
        question = uuid4()

        assert reached_level(
            overview=[question, question, uuid4()], full=[], attempts=right([question])
        ) == (Level.SAVED)

    def test_attempts_at_other_questions_do_not_count(self) -> None:
        overview = ids(3)

        assert reached_level(overview=overview, full=[], attempts=right(ids(3))) == Level.SAVED


class TestAdvance:
    def test_a_level_is_reached_once_with_its_time(self) -> None:
        recognised = advance(LevelState(), Level.RECOGNISED, NOW)
        again = advance(recognised, Level.RECOGNISED, NOW + timedelta(days=1))

        assert recognised == LevelState(Level.RECOGNISED, NOW, None)
        assert again == recognised

    def test_understood_in_one_step_sets_both_times(self) -> None:
        assert advance(LevelState(), Level.UNDERSTOOD, NOW) == LevelState(
            Level.UNDERSTOOD, NOW, NOW
        )

    def test_a_level_never_goes_down(self) -> None:
        understood = LevelState(Level.UNDERSTOOD, NOW, NOW)

        assert advance(understood, Level.SAVED, NOW + timedelta(days=1)) == understood
        assert advance(understood, Level.RECOGNISED, NOW + timedelta(days=1)) == understood

    def test_the_second_level_keeps_the_first_time(self) -> None:
        later = NOW + timedelta(days=3)
        state = advance(advance(LevelState(), Level.RECOGNISED, NOW), Level.UNDERSTOOD, later)

        assert state == LevelState(Level.UNDERSTOOD, NOW, later)

    @pytest.mark.parametrize(
        ("level", "recognised_at", "understood_at"),
        [
            (Level.SAVED, NOW, None),
            (Level.SAVED, None, NOW),
            (Level.RECOGNISED, None, None),
            (Level.RECOGNISED, NOW, NOW),
            (Level.UNDERSTOOD, NOW, None),
            (Level.UNDERSTOOD, None, NOW),
        ],
    )
    def test_a_state_whose_times_disagree_with_its_level_is_refused(
        self, level: Level, recognised_at: datetime | None, understood_at: datetime | None
    ) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            LevelState(level, recognised_at, understood_at)
        assert refused.value.refusal == "level_timestamps_inconsistent"

    @given(
        steps=st.lists(
            st.sampled_from([Level.SAVED, Level.RECOGNISED, Level.UNDERSTOOD]), max_size=12
        )
    )
    def test_any_sequence_of_results_gives_a_non_decreasing_level(self, steps: list[Level]) -> None:
        state = LevelState()
        for step in steps:
            following = advance(state, step, NOW)
            assert following.level.rank >= state.level.rank
            assert following.level.rank >= step.rank
            state = following


class TestGradeAnswer:
    def test_the_chosen_stored_index_is_compared_with_the_correct_one(self) -> None:
        assert grade_answer(2, 2, 4)
        assert not grade_answer(1, 2, 4)

    @pytest.mark.parametrize("chosen", [-1, 3, 4, 100])
    def test_an_index_outside_the_options_is_refused_not_marked_wrong(self, chosen: int) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            grade_answer(chosen, 0, 3)
        assert refused.value.refusal == "option_out_of_range"

    def test_a_boolean_is_not_an_index(self) -> None:
        with pytest.raises(LibraryRefusedError):
            grade_answer(True, 1, 3)

    @pytest.mark.parametrize("count", [0, 2, 5])
    def test_a_question_has_three_or_four_options(self, count: int) -> None:
        with pytest.raises(LibraryRefusedError):
            grade_answer(0, 0, count)


class TestOptionOrder:
    @given(
        question=st.uuids(),
        attempts=st.integers(min_value=0, max_value=1000),
        count=st.sampled_from([3, 4]),
    )
    def test_it_is_a_permutation_of_the_stored_indexes(
        self, question: UUID, attempts: int, count: int
    ) -> None:
        assert sorted(option_order(question, attempts, count)) == list(range(count))

    @given(
        question=st.uuids(),
        attempts=st.integers(min_value=0, max_value=500),
        count=st.sampled_from([3, 4]),
    )
    def test_it_is_deterministic_and_changes_with_every_attempt(
        self, question: UUID, attempts: int, count: int
    ) -> None:
        assert option_order(question, attempts, count) == option_order(question, attempts, count)
        assert option_order(question, attempts, count) != option_order(
            question, attempts + 1, count
        )

    @pytest.mark.parametrize("count", [3, 4])
    def test_every_option_stands_in_every_place_over_one_round(self, count: int) -> None:
        question = UUID("00000000-0000-7000-8000-000000000001")

        orders = [option_order(question, attempt, count) for attempt in range(count)]

        for place in range(count):
            assert {order[place] for order in orders} == set(range(count))

    def test_it_does_not_put_the_first_option_first_for_every_question(self) -> None:
        firsts = {option_order(uuid4(), 0, 4)[0] for _ in range(60)}

        assert len(firsts) > 1

    def test_a_pinned_order_documents_the_shuffle(self) -> None:
        question = UUID("00000000-0000-7000-8000-000000000001")

        assert [option_order(question, attempt, 4) for attempt in range(5)] == [
            option_order(question, 0, 4),
            option_order(question, 1, 4),
            option_order(question, 2, 4),
            option_order(question, 3, 4),
            option_order(question, 0, 4),
        ]
        assert option_order(question, 1, 4) == (
            option_order(question, 0, 4)[1:] + option_order(question, 0, 4)[:1]
        )

    @pytest.mark.parametrize(("attempts", "count"), [(-1, 3), (0, 2), (0, 5), (True, 3)])
    def test_bad_arguments_are_refused(self, attempts: int, count: int) -> None:
        with pytest.raises(LibraryRefusedError):
            option_order(uuid4(), attempts, count)


def draft(
    prompt: str = "What is 2 + 2?", options: tuple[str, ...] = ("3", "4", "5"), correct: int = 1
) -> QuestionDraft:
    return QuestionDraft(prompt, options, correct)


def numbered(count: int) -> list[QuestionDraft]:
    return [draft(prompt=f"Question {number}?") for number in range(count)]


class TestQuestionSets:
    def test_an_overview_set_is_exactly_three_questions(self) -> None:
        assert len(validate_question_set(SetKind.OVERVIEW, numbered(3))) == 3
        for count in (0, 2, 4):
            with pytest.raises(LibraryRefusedError) as refused:
                validate_question_set(SetKind.OVERVIEW, numbered(count))
            assert refused.value.refusal == "question_count_invalid"

    def test_a_full_set_is_five_to_twelve_questions(self) -> None:
        for count in (5, 12):
            assert len(validate_question_set(SetKind.FULL, numbered(count))) == count
        for count in (4, 13):
            with pytest.raises(LibraryRefusedError):
                validate_question_set(SetKind.FULL, numbered(count))

    def test_text_is_cleaned_to_one_visible_line(self) -> None:
        dirty = QuestionDraft(
            "  Why\u200b is  the\nsky blue?  ", ("Rayleigh", "Mie\u202e", "Dust"), 0, " Because.  "
        )

        cleaned = validate_question_set(SetKind.OVERVIEW, [dirty, *numbered(2)])[0]

        assert cleaned == QuestionDraft(
            "Why is the sky blue?", ("Rayleigh", "Mie", "Dust"), 0, "Because."
        )

    @pytest.mark.parametrize(
        ("bad", "refusal"),
        [
            (draft(options=("a", "b")), "option_count_invalid"),
            (draft(options=("a", "b", "c", "d", "e")), "option_count_invalid"),
            (draft(options=("a", "A", "b")), "option_duplicated"),
            (draft(options=("a", "", "b")), "option_invalid"),
            (draft(options=("a", "x" * 201, "b")), "option_invalid"),
            (draft(prompt=""), "prompt_invalid"),
            (draft(prompt="x" * 301), "prompt_invalid"),
            (draft(correct=3), "correct_index_invalid"),
            (draft(correct=-1), "correct_index_invalid"),
            (QuestionDraft("Q?", ("a", "b", "c"), 0, "x" * 301), "explanation_invalid"),
        ],
    )
    def test_a_question_that_breaks_a_rule_is_refused(
        self, bad: QuestionDraft, refusal: str
    ) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            validate_question_set(SetKind.OVERVIEW, [bad, *numbered(2)])
        assert refused.value.refusal == refusal

    def test_two_questions_with_the_same_prompt_are_refused(self) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            validate_question_set(
                SetKind.OVERVIEW, [draft(), draft(prompt="what is 2 + 2?"), *numbered(1)]
            )
        assert refused.value.refusal == "question_duplicated"


class TestFacts:
    def test_facts_are_cleaned_and_capped_at_twenty_per_source(self) -> None:
        facts = [FactDraft(f"Term {number}", "Meaning") for number in range(20)]

        assert validate_facts(facts) == tuple(facts)
        with pytest.raises(LibraryRefusedError):
            validate_facts([*facts, FactDraft("One more", "x")])
        with pytest.raises(LibraryRefusedError):
            validate_facts(facts[:5], already=16)

    @pytest.mark.parametrize(
        "bad",
        [
            FactDraft("", "a"),
            FactDraft("a", " "),
            FactDraft("x" * 201, "a"),
            FactDraft("a", "x" * 301),
        ],
    )
    def test_an_empty_or_long_fact_is_refused(self, bad: FactDraft) -> None:
        with pytest.raises(LibraryRefusedError) as refused:
            validate_facts([bad])
        assert refused.value.refusal == "fact_invalid"
