"""Swedish phonetic key and name matching for misheard names (pure, no database)."""

import pytest

from sidekick.contacts.domain.phonetic import phonetic_match, swedish_phonetic_key


@pytest.mark.parametrize(
    ("heard", "name"),
    [
        ("Shell", "Kjell"),
        ("Kjell", "Tjell"),
        ("Chell", "Kjell"),
        ("Sjell", "Kjell"),
        ("Kell", "Kjell"),
        ("Anna", "Ana"),
        ("Philip", "Filip"),
        ("Sofie", "Sophie"),
        ("Axel", "Aksel"),
        ("Cecilia", "Sesilia"),
        ("Carl", "Karl"),
        ("Zara", "Sara"),
        ("Johan", "Joan"),
        ("Wilhelm", "Vilhelm"),
        ("Hjalmar", "Jalmar"),
        ("Gjord", "Jord"),
        ("Skjorta", "Sjorta"),
        ("Édouard", "Edouard"),
        ("Kjell Hansson", "Shell Hansson"),
        ("Shell", "Kjell Hansson"),
    ],
)
def test_phonetic_match_finds_misheard_names(heard: str, name: str) -> None:
    assert phonetic_match(heard, name)


@pytest.mark.parametrize(
    ("heard", "name"),
    [
        ("Kjell", "Karl"),
        ("Shell", "Stella"),
        ("Kjell", "Kjellberg"),
        ("Anna", "Anders"),
        ("Sara", "Sven"),
        ("Lars", "Lasse"),
        ("Kjell", "Johan"),
        ("Chell", "Shelley"),
        ("Sven", "Svensson"),
        ("Kjell", ""),
        ("", "Kjell"),
        ("123", "Kjell"),
    ],
)
def test_phonetic_match_rejects_different_names(heard: str, name: str) -> None:
    assert not phonetic_match(heard, name)


def test_misheard_consonant_clusters_share_one_key() -> None:
    assert swedish_phonetic_key("Kjell") == "Xel"
    assert swedish_phonetic_key("Shell") == "Xel"
    assert swedish_phonetic_key("Tjell") == "Xel"
    assert swedish_phonetic_key("Chell") == "Xel"


def test_rule_examples_have_documented_keys() -> None:
    assert swedish_phonetic_key("Anna") == "ana"
    assert swedish_phonetic_key("Johan") == "joan"
    assert swedish_phonetic_key("Zara") == "sara"
    assert swedish_phonetic_key("Djurgården") == "jurgården"
    assert swedish_phonetic_key("Kjell Hansson") == "Xelhanson"
    assert swedish_phonetic_key("1234 !?") == ""
