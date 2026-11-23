"""The consent the owner gives before check-ins are switched on, and before Claude may read them.

`CONSENT_VERSION` names the text below. Raise it whenever the meaning of a statement changes: an
owner who accepted an older version must accept the new one before the feature is enabled again.
Two separate switches carry two separate texts; the second is off until the owner turns it on.
"""

from __future__ import annotations

from typing import Final

from sidekick.shared.locale import LocalizedText

CONSENT_VERSION: Final = 1

CONSENT_STATEMENTS: Final[tuple[LocalizedText, ...]] = (
    {
        "sv": "Det som sparas är ett tal per fråga och datumet, för varje incheckning.",
        "en": "What is stored is one number per question and the date, for each check-in.",
    },
    {
        "sv": "Det sparas bara på din egen server, i samma databas och säkerhetskopior som "
        "allt annat.",
        "en": "It is stored only on your own server, in the same database and backups as "
        "everything else.",
    },
    {
        "sv": "Ingen annan ser det. Claude ser en sammanfattning bara om du slår på det andra "
        "valet.",
        "en": "Nobody else sees it. Claude sees a summary only if you turn on the second switch.",
    },
    {
        "sv": "Det är en självskattning med egna frågor, inte ett test och ingen diagnos.",
        "en": "It is a self-rating with its own questions, not a test and not a diagnosis.",
    },
    {
        "sv": "Om du raderar dina svar försvinner de ur databasen, men inte ur säkerhetskopior "
        "som redan tagits.",
        "en": "If you erase your answers they leave the database, but not backups already taken.",
    },
    {
        "sv": "Inget ändras automatiskt utifrån dina svar.",
        "en": "Nothing is changed automatically because of your answers.",
    },
)

CLAUDE_ACCESS_STATEMENT: Final[LocalizedText] = {
    "sv": "När det här är på kan Claude läsa sammanfattningen av dina svar när du ber om det. "
    "Det Claude läser skickas till Anthropic som allt annat du berättar för Claude, och "
    "Claudes egen samtalshistorik kan spara det som sägs.",
    "en": "When this is on, Claude can read the summary of your answers when you ask for it. "
    "What Claude reads is sent to Anthropic like anything else you tell Claude, and "
    "Claude's own chat history may keep what is said.",
}


def consent_is_current(accepted_version: int | None) -> bool:
    """True when the owner accepted the version of the text that is in force now."""

    return accepted_version == CONSENT_VERSION
