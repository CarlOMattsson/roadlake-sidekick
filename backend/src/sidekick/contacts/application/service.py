"""Transport-neutral Contact commands and queries."""

import hashlib
from collections.abc import Sequence
from typing import Any
from uuid import UUID

from sidekick.contacts.application.models import CreateContactCommand, UpdateContactCommand
from sidekick.contacts.application.paging import contact_cursor
from sidekick.contacts.application.serialization import contact_to_data
from sidekick.contacts.application.store import ContactStore
from sidekick.contacts.domain.contact import Contact, ContactAlias
from sidekick.contacts.domain.normalization import (
    normalize_context_note,
    normalize_email,
    normalize_name,
    normalize_phone,
    normalize_profile_text,
)
from sidekick.shared.errors import NotFoundError, ValidationError
from sidekick.shared.replay import id_replay_record
from sidekick.shared.types import (
    NAMED_KEY,
    Actor,
    Clock,
    CursorCodec,
    Page,
    TxSession,
    UnsetType,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.work.domain.planning import normalize_tag_filter, normalize_tag_selection
from sidekick.work.domain.tag_assignment import apply_record_tags


class ContactService:
    def __init__(self, store: ContactStore, clock: Clock, cursor_codec: CursorCodec) -> None:
        self.store = store
        self.clock = clock
        self.cursor_codec = cursor_codec

    def _replayed(self, session: TxSession, actor: Actor, result: dict[str, Any]) -> Contact:
        """The Contact a (possibly replayed) write refers to, re-read by id.

        The idempotency record keeps only the id (`id_replay_record`), so a retry returns the
        Contact as it is now, archived or not, rather than a stored copy of its text.
        """

        return self.store.get_contact(
            session, actor.user_id, UUID(result["id"]), include_archived=True
        )

    def list(
        self,
        actor: Actor,
        *,
        q: str | None = None,
        include_archived: bool = False,
        tags: Sequence[str] = (),
        tag_match: str = "any",
        limit: int = 25,
        cursor: str | None = None,
    ) -> Page[Contact]:
        actor.require("contacts:read")
        validate_limit(limit, maximum=100)

        wanted_tags, tag_match = normalize_tag_filter(list(tags), tag_match)
        normalized_query = normalize_name(q)[1] if q else "*"
        query_fingerprint = hashlib.sha256(normalized_query.encode()).hexdigest()
        query_key = f"contacts:v2:q={query_fingerprint}:archived={include_archived}"
        if wanted_tags:
            query_key += f":tags={','.join(wanted_tags)}:match={tag_match}"
        after = self.cursor_codec.decode_keyset(actor.user_id, cursor, query_key, kinds=NAMED_KEY)

        contacts = self.store.transaction(
            lambda session: self.store.list_contacts(
                session,
                actor.user_id,
                limit + 1,
                q,
                include_archived,
                after,
                wanted_tags,
                tag_match,
            )
        )
        if q and not contacts and after is None and not wanted_tags:
            # A misheard name ("Shell" for "Kjell") finds nothing by name or alias: one bounded
            # phonetic page, without a cursor, so the list never pages through fallback hits.
            phonetic = self.store.transaction(
                lambda session: self.store.phonetic_contacts(
                    session, actor.user_id, q, include_archived=include_archived, limit=limit
                )
            )
            return Page(items=phonetic, next_cursor=None)
        return Page(
            *paginate(
                contacts,
                limit,
                lambda last: contact_cursor(self.cursor_codec, actor, last, query_key),
            )
        )

    def get(self, actor: Actor, contact_id: UUID) -> Contact:
        actor.require("contacts:read")
        return self.store.transaction(
            # Detail is also the restore surface. A deliberately requested archived
            # record must remain readable so the owner can recover it from the list.
            lambda session: self.store.get_contact(
                session, actor.user_id, contact_id, include_archived=True
            )
        )

    def create(
        self,
        actor: Actor,
        command: CreateContactCommand,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "display_name": command.display_name,
            "context_note": command.context_note,
            "email": command.email,
            "phone": command.phone,
            "aliases": command.aliases,
        }
        # Only set profile fields are hashed, so a replay recorded before they existed matches.
        for field in ("relationship", "organization", "role", "address"):
            if getattr(command, field) is not None:
                payload[field] = getattr(command, field)
        tags = normalize_tag_selection(command.tags)
        if tags:
            payload["tags"] = list(tags)

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="create_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._create(session, actor, command, tags, correlation_id),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _create(
        self,
        session: TxSession,
        actor: Actor,
        command: CreateContactCommand,
        tags: tuple[str, ...],
        correlation_id: str | None,
    ) -> dict[str, Any]:
        now = self.clock.now()
        disp_val, key_val = normalize_name(command.display_name)
        email_val, email_key = normalize_email(command.email)
        phone_val, phone_key = normalize_phone(command.phone)
        note_val = normalize_context_note(command.context_note)
        relationship_val = normalize_profile_text(command.relationship, "relationship")
        organization_val = normalize_profile_text(command.organization, "organization")
        role_val = normalize_profile_text(command.role, "role")
        address_val = normalize_profile_text(command.address, "address")

        aliases_list: list[ContactAlias] = []
        aliases = command.aliases or []
        if len(aliases) > 20:
            raise ValidationError("maximum of 20 aliases is allowed")
        alias_keys: set[str] = set()
        for value in aliases:
            norm_val, norm_key = normalize_name(value)
            if norm_key in alias_keys:
                raise ValidationError("alias already exists on this contact")
            alias_keys.add(norm_key)
            aliases_list.append(
                ContactAlias(
                    id=new_uuid7(),
                    value=norm_val,
                    created_at=now,
                )
            )

        contact = Contact(
            id=new_uuid7(),
            owner_id=actor.user_id,
            display_name=disp_val,
            display_name_key=key_val,
            context_note=note_val,
            email=email_val,
            email_key=email_key,
            phone=phone_val,
            phone_key=phone_key,
            relationship=relationship_val,
            organization=organization_val,
            role=role_val,
            address=address_val,
            aliases=aliases_list,
            archived=False,
            created_at=now,
            updated_at=now,
            archived_at=None,
            version=1,
        )
        self.store.save_contact(session, contact)
        if tags:
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="contact",
                record_id=contact.id,
                values=tags,
                now=now,
            )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.created",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(contact)

    def update(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        command: UpdateContactCommand,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        changes = command.changes()
        payload = {"contact_id": str(contact_id), "expected_version": expected_version, **changes}
        if not isinstance(command.tags, UnsetType):
            payload["tags"] = list(normalize_tag_selection(command.tags))

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="update_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._update(
                    session, actor, contact_id, expected_version, command, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _update(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        command: UpdateContactCommand,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        now = self.clock.now()
        changes = command.changes()
        # Tags are relations, but part of the Contact's version: a tags-only update advances it too.
        updated = contact.update(now=now, **changes) if changes else contact.retag(now=now)
        self.store.save_contact(session, updated, expected_version=expected_version)
        if not isinstance(command.tags, UnsetType):
            apply_record_tags(
                self.store,
                session,
                owner_id=actor.user_id,
                kind="contact",
                record_id=contact.id,
                values=command.tags,
                now=now,
            )
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.updated",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def archive(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {"contact_id": str(contact_id), "expected_version": expected_version}

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="archive_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._archive(
                    session, actor, contact_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _archive(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        updated = contact.archive(now=self.clock.now())
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.archived",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def restore(
        self,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {"contact_id": str(contact_id), "expected_version": expected_version}

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="restore_contact",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._restore(
                    session, actor, contact_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _restore(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id, include_archived=True)
        if not contact.archived:
            raise NotFoundError("contact not found")
        updated = contact.restore(now=self.clock.now())
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.restored",
            outcome="success",
            target_type="contact",
            target_id=contact.id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def add_alias(
        self,
        actor: Actor,
        contact_id: UUID,
        value: str,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "contact_id": str(contact_id),
            "value": value,
            "expected_version": expected_version,
        }

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="add_contact_alias",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._add_alias(
                    session, actor, contact_id, value, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _add_alias(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        value: str,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        alias_id = new_uuid7()
        updated = contact.add_alias(now=self.clock.now(), value=value, alias_id=alias_id)
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.alias_added",
            outcome="success",
            target_type="contact_alias",
            target_id=alias_id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def remove_alias(
        self,
        actor: Actor,
        contact_id: UUID,
        alias_id: UUID,
        expected_version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> Contact:
        actor.require("contacts:write")
        payload = {
            "contact_id": str(contact_id),
            "alias_id": str(alias_id),
            "expected_version": expected_version,
        }

        def operation(session: TxSession) -> Contact:
            result = self.store.idempotent(
                session,
                actor_id=actor.user_id,
                operation="remove_contact_alias",
                key=idempotency_key,
                payload=payload,
                replay=id_replay_record,
                execute=lambda: self._remove_alias(
                    session, actor, contact_id, alias_id, expected_version, correlation_id
                ),
            )
            return self._replayed(session, actor, result)

        return self.store.transaction(operation)

    def _remove_alias(
        self,
        session: TxSession,
        actor: Actor,
        contact_id: UUID,
        alias_id: UUID,
        expected_version: int,
        correlation_id: str | None,
    ) -> dict[str, Any]:
        contact = self.store.get_contact(session, actor.user_id, contact_id)
        if all(alias.id != alias_id for alias in contact.aliases):
            # An id that is not this Contact's alias (another owner's, another Contact's or made
            # up) removes nothing and must not be recorded as a removal in the audit trail.
            raise NotFoundError("contact alias not found")
        updated = contact.remove_alias(now=self.clock.now(), alias_id=alias_id)
        self.store.save_contact(session, updated, expected_version=expected_version)
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event="contact.alias_removed",
            outcome="success",
            target_type="contact_alias",
            target_id=alias_id,
            related_id=contact_id,
            correlation_id=correlation_id,
        )
        return contact_to_data(updated)

    def waiting_contact_names(self, actor: Actor, contact_ids: Sequence[UUID]) -> dict[UUID, str]:
        """Display names of several waiting Contacts, archived ones included, in one query."""

        actor.require("contacts:read")
        ids = tuple(dict.fromkeys(contact_ids))
        if not ids:
            return {}
        found = self.store.transaction(
            lambda session: self.store.contact_display_names(session, actor.user_id, ids)
        )
        return {contact_id: name for contact_id, (name, _archived) in found.items()}
