"""Unit tests for contact field normalization rules (NFKC, whitespace, casefold, boundaries)."""

import pytest

from sidekick.contacts.domain.normalization import (
    normalize_email,
    normalize_name,
    normalize_phone,
)
from sidekick.shared.errors import ValidationError


def test_normalize_name() -> None:
    # Unicode NFKC, trim leading/trailing whitespace, collapse internal whitespace
    assert normalize_name("  Rasmus  ") == ("Rasmus", "rasmus")
    assert normalize_name("Åsa") == ("Åsa", "åsa")  # NFKC check
    assert normalize_name("John   Doe") == ("John Doe", "john doe")
    assert normalize_name("Straße") == ("Straße", "strasse")
    assert normalize_name("\uff32\uff41\uff53\uff4d\uff55\uff53") == ("Rasmus", "rasmus")

    # Empty name should raise ValidationError
    with pytest.raises(ValidationError):
        normalize_name("   ")

    # Unicode controls are rejected
    with pytest.raises(ValidationError):
        normalize_name("Rasmus\u0000")


def test_normalize_email() -> None:
    # Trim, exact-match key keeps unicode-casefolded email, reject whitespace, exactly one @
    assert normalize_email(" Rasmus@Example.com ") == ("Rasmus@Example.com", "rasmus@example.com")
    assert normalize_email("STRASSE@Example.com") == (
        "STRASSE@Example.com",
        "strasse@example.com",
    )
    assert normalize_email(None) == (None, None)
    assert normalize_email("   ") == (None, None)

    with pytest.raises(ValidationError):
        normalize_email("rasmus example.com")
    with pytest.raises(ValidationError):
        normalize_email("rasmus@example@com")


def test_normalize_phone() -> None:
    # Trim, allow only ASCII digits, spaces, +, -, (, ), .
    # Keep optional leading + plus digits for key
    assert normalize_phone(" +46 (123) 45-67.89 ") == ("+46 (123) 45-67.89", "+46123456789")
    assert normalize_phone(None) == (None, None)
    assert normalize_phone("   ") == (None, None)

    with pytest.raises(ValidationError):
        normalize_phone("abc")
    with pytest.raises(ValidationError):
        normalize_phone("++46")
    with pytest.raises(ValidationError):
        normalize_phone("+ 46")
