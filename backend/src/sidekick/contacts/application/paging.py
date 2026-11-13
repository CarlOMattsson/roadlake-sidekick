"""Keyset cursor shared by the Contact list queries."""

from sidekick.contacts.domain.contact import Contact
from sidekick.shared.types import SORT_KEY_CHARS, Actor, CursorCodec


def contact_cursor(cursor_codec: CursorCodec, actor: Actor, last: Contact, query_key: str) -> str:
    """The cursor after the last Contact served: its name key and id."""

    return cursor_codec.encode_keyset(
        actor.user_id, (last.display_name_key[:SORT_KEY_CHARS], last.id), query_key
    )
