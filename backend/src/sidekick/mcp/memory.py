"""The MCP memory tools: `recall_memory` and the settings tools.

`get_memory_status`, `set_memory_settings` and `exclude_from_memory` sit over
`sidekick.memory.application.settings`, which holds the scope rules (see its docstring). Their first
text line is speakable (D-072: voice mode works through MCP): counts and domain names, never an id,
version or time.

Facts come only from `sidekick.memory.application.recall.recall_verified`, which releases a fact
only when Postgres confirms its source. This module adds each cited record's title and date with
one batched query per kind, and maps the result to the public output. Facts are derived text: the
model reads a cited source before it relies on details. Neither the query nor
the fact text reaches a log record from this module.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Annotated, Literal
from uuid import UUID

from fastmcp import FastMCP
from fastmcp.apps import AppConfig
from fastmcp.tools import ToolResult
from pydantic import Field

from sidekick.mcp.annotations import DESTRUCTIVE, READ, WRITE
from sidekick.mcp.correlation import request_correlation_id_or_new
from sidekick.mcp.results import output_schema, result
from sidekick.mcp.sidekick_app import SIDEKICK_APP_URI
from sidekick.mcp.text import count_phrase, flat
from sidekick.mcp.tool_context import ToolContext
from sidekick.memory.application.recall import (
    KIND_READ_SCOPE,
    CitedSource,
    RecalledFact,
    RecallResult,
    recall_verified,
    source_details,
)
from sidekick.memory.application.settings import (
    DOMAINS,
    MemorySettingsView,
    Removal,
    SettingsOutcome,
    SourceCounts,
    change_settings,
    domain_names,
    memory_status,
    set_exclusion,
)
from sidekick.memory.domain import MemoryKind
from sidekick.memory.ports import MemoryProvider
from sidekick.shared.errors import PermissionDeniedError, ValidationError
from sidekick.shared.types import Actor
from sidekick.structured.base import Output

if TYPE_CHECKING:
    from sidekick.composition import Container


RECALL_DESCRIPTION = (
    "Use when the user asks what they know, said, felt or decided about a person, project, "
    "place or period, or when search finds nothing. Returns short facts from the "
    "user's journal, contacts, projects and selected tasks, each with its source record id. Facts "
    "can lag minutes behind: read the source (get_journal_entry, get_contact_context, get_project) "
    "before relying on details. Not for what is open now: use list_projects or list_tasks. "
    "Trash never appears; archived is marked. "
    "status 'unavailable': memory is down, use search."
)


STATUS_DESCRIPTION = (
    "Use this when the user asks whether memory works or what it covers. Returns which domains "
    "feed memory, whether it is paused, the provider (off, fake, hindsight) and record counts per "
    "kind you may read. version goes to set_memory_settings. The card shows the controls; do not "
    "repeat its figures or call set_memory_settings for it."
)

SETTINGS_DESCRIPTION = (
    "Use this to turn memory on or off per domain (journal, contacts, projects, tasks) or to "
    "pause it. Send expected_version from get_memory_status. Turning a domain off deletes its "
    "facts and a new import is needed to bring them back, so without confirm=true nothing changes "
    "and status 'needs_confirmation' says how much would go. Ask the user, then repeat with "
    "confirm=true. Turning on and pausing need no confirm."
)

EXCLUDE_DESCRIPTION = (
    "Use this to keep one journal entry, contact, project or task out of memory, or back in "
    "with excluded=false. Its facts are removed within minutes; the record is untouched. "
    "Reversible, no confirm."
)

_DOMAIN_NOUNS: dict[str, tuple[str, str]] = {
    "journal": ("journal entry", "journal entries"),
    "contacts": ("contact", "contacts"),
    "projects": ("project", "projects"),
    "tasks": ("task", "tasks"),
}

_KIND_NOUN: dict[MemoryKind, str] = {
    MemoryKind.JOURNAL_ENTRY: "journal entry",
    MemoryKind.CONTACT: "contact",
    MemoryKind.PROJECT: "project",
    MemoryKind.TASK: "task",
}

_EMPTY_SUMMARIES: dict[str, str] = {
    "empty": "No facts in memory for this query.",
    "unavailable": "Memory is unavailable; continue with search.",
    "disabled": "Memory is off.",
    "paused": "Memory is paused.",
}


class RecallSourceRecord(Output):
    """The record a fact was derived from. Title and date come from Postgres, not the provider."""

    kind: MemoryKind
    id: UUID
    title: str | None
    date: str | None
    archived: bool


class RecallFactRecord(Output):
    text: str
    occurred: str | None
    source: RecallSourceRecord


class RecallMemoryResult(Output):
    status: Literal["ok", "empty", "unavailable", "disabled", "paused"]
    facts: list[RecallFactRecord]
    truncated: bool


class MemorySettingsRecord(Output):
    """The owner's memory switches. `version` 0 means no settings were saved yet (all off)."""

    journal: bool
    contacts: bool
    projects: bool
    tasks: bool
    paused: bool
    version: int


class MemorySourceCountRecord(Output):
    kind: MemoryKind
    retained: int
    pending: int
    failed: int
    parked: int
    excluded: int


class MemoryStatusResult(Output):
    settings: MemorySettingsRecord
    provider: Literal["off", "fake", "hindsight"]
    sources: list[MemorySourceCountRecord]


class MemoryRemovalRecord(Output):
    """A domain being switched off and the retained documents that leave memory with it.

    `documents` is null when the caller holds only the domain's write scope (no count is shown).
    """

    domain: Literal["journal", "contacts", "projects", "tasks"]
    documents: int | None


class SetMemorySettingsResult(Output):
    status: Literal["updated", "unchanged", "needs_confirmation"]
    settings: MemorySettingsRecord
    turning_off: list[MemoryRemovalRecord]


class ExcludeFromMemoryResult(Output):
    kind: MemoryKind
    id: UUID
    excluded: bool
    changed: bool


def _settings_record(view: MemorySettingsView) -> MemorySettingsRecord:
    return MemorySettingsRecord(
        journal=view.journal,
        contacts=view.contacts,
        projects=view.projects,
        tasks=view.tasks,
        paused=view.paused,
        version=view.version,
    )


def _provider_name(provider: MemoryProvider | None) -> Literal["off", "fake", "hindsight"]:
    if provider is None:
        return "off"
    return provider.provider_name


def _status_summary(
    settings: MemorySettingsView,
    provider: str,
    counts: Sequence[tuple[MemoryKind, SourceCounts]],
) -> str:
    on = [domain for domain in DOMAINS if settings.enabled(domain)]
    if not on:
        return "Memory is off for every domain."
    state = "paused" if settings.paused else "on"
    head = f"Memory is {state} for {domain_names(on)}"
    if provider == "off":
        head += ", but the memory service is off"
    retained = sum(count.retained for _, count in counts)
    waiting = sum(count.pending for _, count in counts)
    failed = sum(count.failed + count.parked for _, count in counts)
    excluded = sum(count.excluded for _, count in counts)
    parts = [f"{count_phrase(retained, 'record', 'records')} stored"]
    if waiting:
        parts.append(f"{waiting} waiting")
    if failed:
        parts.append(f"{failed} stuck")
    if excluded:
        parts.append(f"{excluded} excluded")
    summary = f"{head}: {', '.join(parts)}."
    if provider == "fake":
        summary += " Memory uses a test provider; nothing reaches the real memory."
    return summary


def _removal_amount(removal: Removal) -> str:
    """The count with its noun, or "all ... facts" when the caller may not see the count."""

    if removal.documents is None:
        return f"all {_DOMAIN_NOUNS[removal.domain][0]} facts"
    return count_phrase(removal.documents, *_DOMAIN_NOUNS[removal.domain])


def _removal_summary(removals: Sequence[Removal]) -> str:
    domains = [removal.domain for removal in removals]
    amounts = [_removal_amount(removal) for removal in removals]
    pronoun = "it" if len(domains) == 1 else "them"
    return (
        f"Turning off {domain_names(domains)} removes {domain_names(amounts)} from memory. "
        f"Turning {pronoun} on again costs a new import. Call again with confirm true."
    )


def _requested_kinds(
    kinds: Sequence[MemoryKind] | None, scopes: frozenset[str]
) -> tuple[MemoryKind, ...]:
    """The kinds this call may recall, with the same rules as the search tool.

    Explicitly requested kinds without read scope refuse the whole call. Omitted kinds narrow to
    the readable ones, and having none at all is forbidden. Error messages name neither scope nor
    input.
    """

    if kinds is None:
        readable = tuple(kind for kind in MemoryKind if KIND_READ_SCOPE[kind] in scopes)
        if not readable:
            raise PermissionDeniedError("forbidden")
        return readable
    if len(set(kinds)) != len(kinds):
        raise ValidationError("kinds must be unique memory kinds")
    if any(KIND_READ_SCOPE[kind] not in scopes for kind in kinds):
        raise PermissionDeniedError("forbidden")
    return tuple(kinds)


def _fact_record(
    fact: RecalledFact, details: Mapping[tuple[MemoryKind, UUID], CitedSource]
) -> RecallFactRecord | None:
    """The public record of a fact, or None when its source is missing from `details`.

    A source trashed between recall and enrichment is absent from `details`. Such a fact is
    dropped, not returned without a title, because it would cite a record that no longer exists.
    """

    source = details.get((fact.source_kind, fact.source_id))
    if source is None:
        return None
    return RecallFactRecord(
        text=fact.text,
        occurred=fact.occurred_start or fact.occurred_end,
        source=RecallSourceRecord(
            kind=fact.source_kind,
            id=fact.source_id,
            title=source.title,
            date=None if source.day is None else source.day.isoformat(),
            archived=fact.archived,
        ),
    )


def _summary(output: RecallMemoryResult) -> str:
    """One short count sentence for the text block; the JSON block carries the facts."""

    if output.status == "ok":
        count = len(output.facts)
        noun = "fact" if count == 1 else "facts"
        more = " More match: narrow the query for the rest." if output.truncated else ""
        return f"Found {count} {noun} in memory.{more}"
    return _EMPTY_SUMMARIES[output.status]


def _recall(
    container: Container,
    actor: Actor,
    *,
    query: str,
    kinds: Sequence[MemoryKind] | None,
    limit: int,
) -> RecallMemoryResult:
    """Recall verified facts for the kinds the actor may read, enriched with source titles."""

    requested = _requested_kinds(kinds, actor.scopes)
    scopes = frozenset(KIND_READ_SCOPE[kind] for kind in requested)
    provider = container.memory
    if provider is None:
        recall = RecallResult(status="disabled")
        details: dict[tuple[MemoryKind, UUID], CitedSource] = {}
    else:
        store = container.memory_store
        with store.read() as session:
            recall = recall_verified(
                store,
                session,
                provider,
                owner_id=actor.user_id,
                query=query,
                limit=limit,
                scopes=scopes,
                correlation_id=request_correlation_id_or_new(),
            )
            details = source_details(store, session, actor.user_id, recall.facts)
    records = [
        record for fact in recall.facts if (record := _fact_record(fact, details)) is not None
    ]
    status = "empty" if recall.status == "ok" and not records else recall.status
    return RecallMemoryResult(status=status, facts=records, truncated=recall.truncated)


def _status_output(
    container: Container, actor: Actor
) -> tuple[MemoryStatusResult, MemorySettingsView, list[tuple[MemoryKind, SourceCounts]]]:
    with container.memory_store.read() as session:
        status = memory_status(container.memory_store, session, actor)
    counts = list(status.counts.items())
    output = MemoryStatusResult(
        settings=_settings_record(status.settings),
        provider=_provider_name(container.memory),
        sources=[
            MemorySourceCountRecord(
                kind=kind,
                retained=count.retained,
                pending=count.pending,
                failed=count.failed,
                parked=count.parked,
                excluded=count.excluded,
            )
            for kind, count in counts
        ],
    )
    return output, status.settings, counts


def _settings_outcome_summary(outcome: SettingsOutcome) -> str:
    """The speakable sentence for a settings change, by status."""

    if outcome.status == "needs_confirmation":
        return _removal_summary(outcome.turning_off)
    if outcome.status == "unchanged":
        return "Memory settings were already like that; nothing changed."
    if outcome.turning_off:
        domains = domain_names([removal.domain for removal in outcome.turning_off])
        return f"Memory is off for {domains}; its facts are removed within minutes."
    return "Memory settings saved."


def _register_recall_memory(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="recall_memory",
        description=RECALL_DESCRIPTION,
        output_schema=output_schema(RecallMemoryResult),
        annotations=READ,
    )
    @ctx.instrument("recall_memory")
    def recall_memory(
        query: Annotated[str, Field(min_length=2, max_length=300)],
        kinds: Annotated[list[MemoryKind], Field(min_length=1, max_length=4)] | None = None,
        limit: Annotated[int, Field(ge=1, le=20)] = 8,
    ) -> ToolResult:
        output = _recall(ctx.container, ctx.actor_provider(), query=query, kinds=kinds, limit=limit)
        return result(output.model_dump(mode="json"), _summary(output))


def _register_get_memory_status(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="get_memory_status",
        description=STATUS_DESCRIPTION,
        output_schema=output_schema(MemoryStatusResult),
        annotations=READ,
        app=AppConfig(resource_uri=SIDEKICK_APP_URI),
    )
    @ctx.instrument("get_memory_status")
    def get_memory_status() -> ToolResult:
        output, settings, counts = _status_output(ctx.container, ctx.actor_provider())
        return result(
            output.model_dump(mode="json"),
            _status_summary(settings, output.provider, counts),
        )


def _register_set_memory_settings(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="set_memory_settings",
        description=SETTINGS_DESCRIPTION,
        output_schema=output_schema(SetMemorySettingsResult),
        annotations=DESTRUCTIVE,
    )
    @ctx.instrument("set_memory_settings")
    def set_memory_settings(
        expected_version: Annotated[int, Field(ge=0)],
        journal: bool | None = None,
        contacts: bool | None = None,
        projects: bool | None = None,
        tasks: bool | None = None,
        paused: bool | None = None,
        confirm: bool = False,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        requested = {
            "journal": journal,
            "contacts": contacts,
            "projects": projects,
            "tasks": tasks,
            "paused": paused,
        }
        changes = {name: value for name, value in requested.items() if value is not None}
        with ctx.container.memory_store.begin() as session:
            outcome = change_settings(
                ctx.container.memory_store,
                session,
                actor,
                changes=changes,
                expected_version=expected_version,
                confirm=confirm,
                now=datetime.now(UTC),
                correlation_id=request_correlation_id_or_new(),
            )
        output = SetMemorySettingsResult(
            status=outcome.status,
            settings=_settings_record(outcome.settings),
            turning_off=[
                MemoryRemovalRecord(domain=removal.domain, documents=removal.documents)
                for removal in outcome.turning_off
            ],
        )
        return result(output.model_dump(mode="json"), _settings_outcome_summary(outcome))


def _register_exclude_from_memory(mcp: FastMCP, ctx: ToolContext) -> None:
    @mcp.tool(
        name="exclude_from_memory",
        description=EXCLUDE_DESCRIPTION,
        output_schema=output_schema(ExcludeFromMemoryResult),
        annotations=WRITE,
    )
    @ctx.instrument("exclude_from_memory")
    def exclude_from_memory(
        kind: MemoryKind,
        id: UUID,
        excluded: bool = True,
    ) -> ToolResult:
        actor = ctx.actor_provider()
        key = ctx.container.settings.memory_id_derivation_key
        with ctx.container.memory_store.begin() as session:
            outcome = set_exclusion(
                ctx.container.memory_store,
                session,
                actor,
                kind=kind,
                source_id=id,
                excluded=excluded,
                id_key=key.get_secret_value().encode("utf-8") if key is not None else None,
                now=datetime.now(UTC),
                correlation_id=request_correlation_id_or_new(),
            )
        output = ExcludeFromMemoryResult(
            kind=outcome.kind,
            id=outcome.source_id,
            excluded=outcome.excluded,
            changed=outcome.changed,
        )
        name = flat(outcome.title or _KIND_NOUN[kind], limit=60)
        if excluded:
            summary = f"{name} is now kept out of memory; its facts are removed within minutes."
        else:
            summary = f"{name} is back in memory; it is imported again shortly."
        return result(output.model_dump(mode="json"), summary)


_REGISTRARS = (
    _register_recall_memory,
    _register_get_memory_status,
    _register_set_memory_settings,
    _register_exclude_from_memory,
)


def register_memory_tools(mcp: FastMCP, ctx: ToolContext) -> None:
    """Register the four memory tools: recall and the settings tools."""
    for register in _REGISTRARS:
        register(mcp, ctx)
