"""Keyset cursor shared by the Contact list queries."""

from collections.abc import Sequence

from sidekick.contacts.domain.contact import Contact
from sidekick.shared.types import SORT_KEY_CHARS, Actor, CursorCodec


def contact_cursor(
    cursor_codec: CursorCodec,
    actor: Actor,
    contacts: Sequence[Contact],
    limit: int,
    query_key: str,
) -> str | None:
    """The cursor after the last Contact served (name key, id), or None on the last page."""

    if len(contacts) <= limit:
        return None
    last = contacts[limit - 1]
    return cursor_codec.encode_keyset(
        actor.user_id, (last.display_name_key[:SORT_KEY_CHARS], last.id), query_key
    )
