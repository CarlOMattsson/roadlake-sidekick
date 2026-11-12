"""The app language (`SIDEKICK_MCP_APP_LOCALE`) and the texts that follow it.

Swedish is the default and the source language; English is the reviewed translation. A text that
depends on the language is a `{"sv": ..., "en": ...}` pair, so the two can never drift apart by key.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Literal

AppLocale = Literal["sv", "en"]
LocalizedText = Mapping[AppLocale, str]

DEFAULT_LOCALE: AppLocale = "sv"


def localized(text: LocalizedText, locale: AppLocale) -> str:
    """The text of the pair in the chosen language."""

    return text[locale]
