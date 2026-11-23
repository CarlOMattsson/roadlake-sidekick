"""The instrument catalogue: both languages everywhere, and answer validation that is total."""

import re

import pytest
from hypothesis import given
from hypothesis import strategies as st

from sidekick.checkins.domain.consent import (
    CLAUDE_ACCESS_STATEMENT,
    CONSENT_STATEMENTS,
    CONSENT_VERSION,
    consent_is_current,
)
from sidekick.checkins.domain.instruments import (
    CATALOGUE,
    KEY_LENGTH_LIMIT,
    OWN_V1,
    AnswerProblem,
    Instrument,
    InvalidAnswerError,
    find_instrument,
    validate_answers,
)

KEY = re.compile(r"[a-z][a-z0-9_]*")
# Distinctive phrases of a published five-item well-being form; the own questions must not echo it.
BORROWED_PHRASES = (
    "cheerful",
    "calm and relaxed",
    "active and vigorous",
    "fresh and rested",
    "things that interest me",
)


def _texts(instrument: Instrument) -> list[dict[str, str]]:
    found: list[dict[str, str]] = [dict(instrument.disclaimer)]
    for question in instrument.questions:
        found += [
            dict(question.name),
            dict(question.text),
            dict(question.anchors.low),
            dict(question.anchors.high),
        ]
    return found


def test_the_own_instrument_asks_the_four_questions_on_a_one_to_five_scale() -> None:
    assert [item.key for item in OWN_V1.questions] == ["energy", "mood", "sleep", "stress"]
    assert all((item.minimum, item.maximum) == (1, 5) for item in OWN_V1.questions)
    assert OWN_V1.validated is False


@pytest.mark.parametrize("instrument", CATALOGUE, ids=lambda item: f"{item.id}-{item.version}")
def test_every_catalogue_text_exists_in_both_languages(instrument: Instrument) -> None:
    for pair in _texts(instrument):
        assert set(pair) == {"sv", "en"}
        assert all(text.strip() for text in pair.values())


def test_the_consent_texts_exist_in_both_languages() -> None:
    for pair in (*CONSENT_STATEMENTS, CLAUDE_ACCESS_STATEMENT):
        assert set(pair) == {"sv", "en"}
        assert all(text.strip() for text in pair.values())


@pytest.mark.parametrize("instrument", CATALOGUE, ids=lambda item: f"{item.id}-{item.version}")
def test_keys_fit_the_columns_and_are_unique(instrument: Instrument) -> None:
    keys = [item.key for item in instrument.questions]
    assert len(set(keys)) == len(keys)
    for key in (instrument.id, *keys):
        assert KEY.fullmatch(key)
        assert len(key) <= KEY_LENGTH_LIMIT
    assert all(item.minimum < item.maximum <= 10 for item in instrument.questions)
    assert all(item.minimum >= 0 for item in instrument.questions)


def test_no_two_catalogue_entries_share_an_id_and_version() -> None:
    pairs = [(item.id, item.version) for item in CATALOGUE]
    assert len(set(pairs)) == len(pairs)


def test_the_own_wording_is_not_a_published_form() -> None:
    text = " ".join(pair["en"].lower() for pair in _texts(OWN_V1))
    assert not [phrase for phrase in BORROWED_PHRASES if phrase in text]


def test_the_disclaimer_says_it_is_not_validated_and_not_a_diagnosis() -> None:
    assert OWN_V1.disclaimer["sv"] == "Egna frågor, inte ett validerat formulär och ingen diagnos."
    assert OWN_V1.disclaimer["en"] == "Own questions, not a validated form and not a diagnosis."


def test_find_instrument_by_id_and_version() -> None:
    assert find_instrument("own") is OWN_V1
    assert find_instrument("own", 1) is OWN_V1
    assert find_instrument("own", 2) is None
    assert find_instrument("who5") is None


def test_valid_answers_come_back_in_question_order() -> None:
    answers = {"stress": 5, "energy": 1, "mood": 3}
    assert list(validate_answers(OWN_V1, answers).items()) == [
        ("energy", 1),
        ("mood", 3),
        ("stress", 5),
    ]


def test_a_partly_answered_checkin_is_allowed() -> None:
    assert validate_answers(OWN_V1, {"sleep": 4}) == {"sleep": 4}


@pytest.mark.parametrize(
    ("answers", "problem"),
    [
        ({}, AnswerProblem.NO_ANSWERS),
        ({"hunger": 3}, AnswerProblem.UNKNOWN_QUESTION),
        ({"energy": 3, "hunger": 3}, AnswerProblem.UNKNOWN_QUESTION),
        ({"energy": 0}, AnswerProblem.OUT_OF_RANGE),
        ({"energy": 6}, AnswerProblem.OUT_OF_RANGE),
        ({"energy": -1}, AnswerProblem.OUT_OF_RANGE),
        ({"energy": 3.0}, AnswerProblem.NOT_AN_INTEGER),
        ({"energy": "3"}, AnswerProblem.NOT_AN_INTEGER),
        ({"energy": None}, AnswerProblem.NOT_AN_INTEGER),
        ({"energy": True}, AnswerProblem.NOT_AN_INTEGER),
        ({"energy": [3]}, AnswerProblem.NOT_AN_INTEGER),
    ],
)
def test_a_bad_answer_set_is_refused_with_a_closed_problem(
    answers: dict[str, object], problem: AnswerProblem
) -> None:
    with pytest.raises(InvalidAnswerError) as caught:
        validate_answers(OWN_V1, answers)
    assert caught.value.problem is problem
    assert caught.value.code == "invalid_answer"


def test_a_refusal_never_names_a_key_or_a_value() -> None:
    with pytest.raises(InvalidAnswerError) as caught:
        validate_answers(OWN_V1, {"energy": 4242, "mood": 3})
    shown = f"{caught.value} {caught.value!r} {caught.value.args}"
    assert "4242" not in shown
    assert "energy" not in shown
    assert "mood" not in shown


@given(
    st.dictionaries(
        st.one_of(st.sampled_from(["energy", "mood", "sleep", "stress"]), st.text(max_size=8)),
        st.one_of(
            st.integers(),
            st.floats(allow_nan=True),
            st.booleans(),
            st.none(),
            st.text(max_size=4),
        ),
        max_size=6,
    )
)
def test_validation_is_total_and_only_returns_values_in_range(answers: dict[str, object]) -> None:
    try:
        checked = validate_answers(OWN_V1, answers)
    except InvalidAnswerError:
        return
    assert checked
    assert all(isinstance(value, int) and 1 <= value <= 5 for value in checked.values())
    assert set(checked) == set(answers)


def test_the_consent_version_is_current_only_when_it_matches() -> None:
    assert consent_is_current(CONSENT_VERSION)
    assert not consent_is_current(None)
    assert not consent_is_current(CONSENT_VERSION - 1)
    assert not consent_is_current(CONSENT_VERSION + 1)
