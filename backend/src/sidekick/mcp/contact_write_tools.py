"""The Contact write tools: create, update, archive, restore and aliases."""

from __future__ import annotations

from typing import Annotated, cast
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult

from sidekick.contacts.application.models import CreateContactCommand, UpdateContactCommand
from sidekick.contacts.domain.contact import Contact
from sidekick.mcp.annotations import DESTRUCTIVE, WRITE
from sidekick.mcp.contact_records import (
    Address,
    ContactChanges,
    ContactResult,
    Organization,
    Relationship,
    Role,
    contact_result,
)
from sidekick.mcp.contact_text import contact_summary
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.idempotency import IdempotencyKey
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import flat
from sidekick.mcp.tool_context import ToolContext
from sidekick.shared.text_guard import NoImageData
from sidekick.shared.types import UNSET, UnsetType
from sidekick.structured.tags import TagsInput


def _update_command(changes: ContactChanges) -> UpdateContactCommand:
    """Fields the caller sent are mapped; the rest stay UNSET."""

    def sent(name: str) -> str | None | UnsetType:
        return getattr(changes, name) if name in changes.model_fields_set else UNSET

    return UpdateContactCommand(
        display_name=cast(str, sent("display_name")),
        context_note=sent("context_note"),
        email=sent("email"),
        phone=sent("phone"),
        relationship=sent("relationship"),
        organization=sent("organization"),
        role=sent("role"),
        address=sent("address"),
        tags=tuple(changes.tags) if "tags" in changes.model_fields_set else UNSET,
    )


def _contact_result(ctx: ToolContext, contact: Contact) -> ContactResult:
    """The tool result for a just-written Contact, with its tags.

    Every Contact write tool needs `contacts:read` for its reply (`reply_scopes`), which is also
    what reading a Contact's tags takes.
    """

    tags = ctx.container.work_tags.for_record(ctx.actor_provider(), "contact", contact.id)
    return contact_result(contact, [tag.slug for tag in tags])


def _register_create_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="create_contact",
        description=(
            "Use this only when the user has asked to create one Contact. Optional aliases, "
            "metadata and tags are stored only in Sidekick; no message or external lookup "
            "occurs. Safe to retry with the same key and payload."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("create_contact")
    def create_contact(
        display_name: Annotated[str, NoImageData],
        idempotency_key: IdempotencyKey,
        context_note: Annotated[str | None, NoImageData] = None,
        email: Annotated[str | None, NoImageData] = None,
        phone: Annotated[str | None, NoImageData] = None,
        aliases: list[Annotated[str, NoImageData]] | None = None,
        relationship: Relationship = None,
        organization: Organization = None,
        role: Role = None,
        address: Address = None,
        tags: TagsInput | None = None,
    ) -> ToolResult:
        cmd = CreateContactCommand(
            display_name=display_name,
            context_note=context_note,
            email=email,
            phone=phone,
            aliases=aliases,
            relationship=relationship,
            organization=organization,
            role=role,
            address=address,
            tags=tuple(tags or ()),
        )
        contact = ctx.container.contacts.create(
            ctx.actor_provider(),
            command=cmd,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(ctx, contact)
        record = structured.contact
        return result(
            structured.model_dump(mode="json"),
            contact_summary(f"Created contact {flat(record.display_name)}.", record),
        )


def _register_update_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="update_contact",
        description=(
            "Use this for explicit edits to one known owned active Contact. Supply the "
            "observed version; omitted fields stay unchanged and explicit null clears "
            "optional metadata. tags replaces the tag set, [] clears it, null is refused. Do "
            "not use this for aliases or work links."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("update_contact")
    def update_contact(
        contact_id: UUID,
        expected_version: int,
        idempotency_key: IdempotencyKey,
        changes: ContactChanges,
    ) -> ToolResult:
        contact = ctx.container.contacts.update(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            command=_update_command(changes),
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(ctx, contact)
        record = structured.contact
        return result(
            structured.model_dump(mode="json"),
            contact_summary(f"Updated contact {flat(record.display_name)}.", record),
        )


def _register_archive_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="archive_contact",
        description=(
            "Use this when the user explicitly wants to hide one known Contact from active views. "
            "Archive is reversible, preserves typed links, and does not delete Contact data."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("archive_contact")
    def archive_contact(
        contact_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        contact = ctx.container.contacts.archive(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(ctx, contact)
        # The version changes on archive, so the id and new version stay in the text for restore.
        record = structured.contact
        return result(
            structured.model_dump(mode="json"),
            contact_summary(
                f"Archived contact {flat(record.display_name)}; "
                "its data and links remain restorable.",
                record,
            ),
        )


def _register_restore_contact(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="restore_contact",
        description=(
            "Use this when the user explicitly wants to return one archived owned Contact "
            "to active "
            "views. It does not restore or modify related Projects or Tasks."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("restore_contact")
    def restore_contact(
        contact_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        contact = ctx.container.contacts.restore(
            ctx.actor_provider(),
            contact_id=contact_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(ctx, contact)
        record = structured.contact
        return result(
            structured.model_dump(mode="json"),
            contact_summary(f"Restored contact {flat(record.display_name)}.", record),
        )


def _register_add_contact_alias(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="add_contact_alias",
        description=(
            "Use this to add one alternative name to a known active Contact using its "
            "current version. Equivalent aliases on the same Contact are not duplicated; "
            "the same alias may identify "
            "other Contacts."
        ),
        output_schema=output_schema(ContactResult),
        annotations=WRITE,
    )
    @ctx.instrument("add_contact_alias")
    def add_contact_alias(
        contact_id: UUID, value: str, expected_version: int, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        contact = ctx.container.contacts.add_alias(
            ctx.actor_provider(),
            contact_id=contact_id,
            value=value,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        structured = _contact_result(ctx, contact)
        record = structured.contact
        return result(
            structured.model_dump(mode="json"),
            contact_summary(f"Added the Contact alias to {flat(record.display_name)}.", record),
        )


def _register_remove_contact_alias(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="remove_contact_alias",
        description=(
            "Use this only when the user wants to remove one known alias ID from an active "
            "Contact. "
            "It deletes that alias record but not the Contact or any work link."
        ),
        output_schema=output_schema(ContactResult),
        annotations=DESTRUCTIVE,
        app=AppConfig(visibility=["app"]),
    )
    @ctx.instrument("remove_contact_alias")
    def remove_contact_alias(
        contact_id: UUID, alias_id: UUID, expected_version: int, idempotency_key: IdempotencyKey
    ) -> ToolResult:
        contact = ctx.container.contacts.remove_alias(
            ctx.actor_provider(),
            contact_id=contact_id,
            alias_id=alias_id,
            expected_version=expected_version,
            idempotency_key=idempotency_key,
            correlation_id=request_correlation_id_or_new(),
        )
        return result(
            _contact_result(ctx, contact).model_dump(mode="json"), "Removed the Contact alias."
        )


def register_contact_write_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register create, update, archive, restore and the two alias tools."""

    _register_create_contact(mcp, ctx)
    _register_update_contact(mcp, ctx)
    _register_archive_contact(mcp, ctx)
    _register_restore_contact(mcp, ctx)
    _register_add_contact_alias(mcp, ctx)
    _register_remove_contact_alias(mcp, ctx)
