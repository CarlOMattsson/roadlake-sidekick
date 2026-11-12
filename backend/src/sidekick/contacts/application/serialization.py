"""Contact to plain data, for idempotency replays and for transports."""

from typing import Any

from sidekick.contacts.domain.contact import Contact


def contact_to_data(contact: Contact) -> dict[str, Any]:
    return {
        "id": str(contact.id),
        "owner_id": str(contact.owner_id),
        "display_name": contact.display_name,
        "display_name_key": contact.display_name_key,
        "context_note": contact.context_note,
        "email": contact.email,
        "email_key": contact.email_key,
        "phone": contact.phone,
        "phone_key": contact.phone_key,
        "relationship": contact.relationship,
        "organization": contact.organization,
        "role": contact.role,
        "address": contact.address,
        "aliases": [
            {
                "id": str(alias.id),
                "value": alias.value,
                "created_at": alias.created_at.isoformat(),
            }
            for alias in contact.aliases
        ],
        "archived": contact.archived,
        "created_at": contact.created_at.isoformat(),
        "updated_at": contact.updated_at.isoformat(),
        "archived_at": contact.archived_at.isoformat() if contact.archived_at else None,
        "version": contact.version,
    }


def contact_public_data(contact: Contact) -> dict[str, Any]:
    data = contact_to_data(contact)
    data.pop("owner_id")
    data.pop("display_name_key")
    data.pop("email_key")
    data.pop("phone_key")
    return data
