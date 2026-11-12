"""Property-based tests asserting Contact normalization invariants."""

import unicodedata

from hypothesis import given
from hypothesis import strategies as st

from sidekick.contacts.domain.normalization import normalize_name


@given(
    st.text(alphabet=st.characters(categories=("Lu", "Ll", "Nd", "Zs")), min_size=1, max_size=80)
)
def test_normalize_name_is_idempotent_and_casefolded(value: str) -> None:
    if not " ".join(unicodedata.normalize("NFKC", value).split()):
        return
    display, key = normalize_name(value)
    second_display, second_key = normalize_name(display)
    assert second_display == display
    assert second_key == key == display.casefold()
