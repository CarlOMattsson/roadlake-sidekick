"""Search query parsing and kind/scope resolution rules, without database or transport."""

import pytest

from sidekick.search.domain import KIND_SCOPE, Kind, parse_query, resolve_kinds
from sidekick.shared.errors import PermissionDeniedError, ValidationError

ALL_SCOPES = frozenset({"tasks:read", "projects:read", "contacts:read", "journal:read"})


def test_operator_characters_are_stripped_from_terms() -> None:
    query = parse_query('nät:* & "sök" | (klocka)! <-> !x')

    assert query.terms == ("nät", "sök", "klocka")
    for term in query.terms:
        assert term.isalnum()


def test_sql_and_tsquery_punctuation_never_survives() -> None:
    query = parse_query("x' OR 1=1 -- ';DROP TABLE tasks; \\ @@ ::")

    assert query.terms == ("OR", "11", "DROP", "TABLE", "tasks")
    for term in query.terms:
        assert term.isalnum()


def test_operator_only_tokens_do_not_count_toward_the_term_cap() -> None:
    query = parse_query("& | ! <-> :* ab cd")

    assert query.terms == ("ab", "cd")


def test_digits_and_letters_are_kept() -> None:
    query = parse_query("2026 mars")

    assert query.terms == ("2026", "mars")


def test_nfc_normalization_composes_decomposed_swedish_letters() -> None:
    decomposed = "bök"

    query = parse_query(decomposed)

    assert query.terms == ("bök",)
    assert query.length == len("bök")


def test_terms_are_capped_at_eight() -> None:
    raw = " ".join(f"term{index}" for index in range(10))

    query = parse_query(raw)

    assert query.term_count == 8
    assert query.terms == tuple(f"term{index}" for index in range(8))


def test_cap_applies_after_dropping_unusable_tokens() -> None:
    raw = "& & & & & & & & & & & & ab cd"

    query = parse_query(raw)

    assert query.terms == ("ab", "cd")


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "a", "a b", "&&", "! | :*", "\u00a0", "\t\n"],
)
def test_query_without_a_usable_term_is_too_short(raw: str) -> None:
    with pytest.raises(ValueError, match="too short"):
        parse_query(raw)


def test_surrounding_whitespace_is_ignored() -> None:
    query = parse_query("   faktura   ")

    assert query.terms == ("faktura",)
    assert query.length == len("faktura")


def test_kind_scope_covers_every_kind_with_its_read_scope() -> None:
    assert set(KIND_SCOPE) == set(Kind)
    assert KIND_SCOPE == {
        Kind.TASK: "tasks:read",
        Kind.PROJECT: "projects:read",
        Kind.CONTACT: "contacts:read",
        Kind.JOURNAL: "journal:read",
    }


def test_omitted_kinds_search_every_allowed_kind_in_canonical_order() -> None:
    assert resolve_kinds(None, ALL_SCOPES) == (
        Kind.TASK,
        Kind.PROJECT,
        Kind.CONTACT,
        Kind.JOURNAL,
    )


def test_omitted_kinds_silently_skip_kinds_without_scope() -> None:
    assert resolve_kinds(None, {"tasks:read", "journal:read"}) == (Kind.TASK, Kind.JOURNAL)


def test_omitted_kinds_without_any_scope_is_forbidden() -> None:
    with pytest.raises(PermissionDeniedError, match="forbidden"):
        resolve_kinds(None, set())


def test_omitted_kinds_with_only_unrelated_scopes_is_forbidden() -> None:
    with pytest.raises(PermissionDeniedError, match="forbidden"):
        resolve_kinds(None, {"tasks:write", "lifecycle:read"})


def test_explicit_kinds_keep_requested_order() -> None:
    assert resolve_kinds(["contact", "task"], ALL_SCOPES) == (Kind.CONTACT, Kind.TASK)


def test_explicit_kind_without_scope_rejects_the_whole_call() -> None:
    with pytest.raises(PermissionDeniedError, match="forbidden"):
        resolve_kinds(["task", "journal"], {"tasks:read"})


def test_explicit_single_kind_without_scope_is_forbidden() -> None:
    with pytest.raises(PermissionDeniedError, match="forbidden"):
        resolve_kinds(["journal"], {"tasks:read"})


def test_explicit_kind_with_scope_is_allowed() -> None:
    assert resolve_kinds(["project"], {"projects:read"}) == (Kind.PROJECT,)


def test_empty_kinds_list_is_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_kinds([], ALL_SCOPES)


def test_duplicate_kinds_are_a_validation_error() -> None:
    with pytest.raises(ValidationError):
        resolve_kinds(["task", "task"], ALL_SCOPES)


def test_unknown_kind_is_a_validation_error_without_echoing_input() -> None:
    with pytest.raises(ValidationError) as error:
        resolve_kinds(["secret-kind"], ALL_SCOPES)

    assert "secret-kind" not in str(error.value)
