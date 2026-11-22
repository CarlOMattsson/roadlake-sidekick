"""Deterministic screening of what a runner proposes, before any model check.

Screening has two outcomes for one proposal. It is *refused*, with a closed code, when it cannot
be a suggestion at all (unknown effect, bad schema, a reference that is not the owner's, a run
that is not open, a cap). Or it is *kept*, with its text normalised and a set of *flags* that say
why a person should look twice. A flagged card is never part of a group approval, is never applied
automatically and cannot be decided by a model tool. The flag list is closed and versioned: a new
flag is a new code, never a change of meaning for an old one.

The patterns here are a signal, not the control. The control is that an effect can only be one of
the catalogue's, which can all be undone, and that the owner decides.
"""

import base64
import binascii
import codecs
import re
import unicodedata
from collections import Counter
from collections.abc import Collection, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from enum import StrEnum
from typing import cast
from uuid import UUID

from sidekick.automations.domain.effects import (
    MAX_DATAPOINT_REFS,
    MAX_RATIONALE_CHARS,
    CreateTaskV1,
    EffectKind,
    ParsedPayload,
    PayloadProblem,
    contact_email,
    free_text,
    parse_payload,
    project_reference,
    resolve_effect,
)
from sidekick.automations.domain.text import (
    decoded_readings,
    detection_readings,
    folded_forms,
    match_key,
    normalise_line,
)
from sidekick.contacts.domain.normalization import normalize_email
from sidekick.work.domain.ai_spec import clean_text

FLAG_LIST_VERSION = 1
LARGE_BATCH_LIMIT = 10
"""More suggestions than this from one source are flagged."""


class ScreeningFlag(StrEnum):
    CONTAINS_LINK = "contains_link"
    PAYMENT_RELATED = "payment_related"
    CONTACT_DETAIL_UNVERIFIED = "contact_detail_unverified"
    HOMOGLYPH_DOMAIN = "homoglyph_domain"
    INSTRUCTION_LIKE_TEXT = "instruction_like_text"
    DUPLICATE_EXISTING = "duplicate_existing"
    LARGE_BATCH = "large_batch"


class RejectionCode(StrEnum):
    SCHEMA_INVALID = "schema_invalid"
    EFFECT_UNKNOWN = "effect_unknown"
    EFFECT_NOT_ALLOWED = "effect_not_allowed"
    TOO_LONG = "too_long"
    REFERENCE_UNUSABLE = "reference_unusable"
    RUN_NOT_RUNNING = "run_not_running"
    DATAPOINT_NOT_IN_RUN = "datapoint_not_in_run"
    OVER_RUN_CAP = "over_run_cap"


@dataclass(frozen=True, slots=True)
class SourceInfo:
    """What screening knows about the source of a datapoint. Never its text."""

    kind: str
    fingerprint: str
    sender_domain: str | None = None
    """The domain of the sender, for a mail datapoint."""


@dataclass(frozen=True, slots=True)
class ScreeningContext:
    """What the application looked up before screening one call of `record results`."""

    allowed_effects: frozenset[EffectKind]
    run_open: bool
    max_suggestions: int
    already_recorded: int
    datapoint_sources: Mapping[UUID, SourceInfo]
    """The datapoints of this run, and nothing else."""
    usable_project_ids: frozenset[UUID] = frozenset()
    """Of the projects the proposals name, those that are the owner's and not in the trash."""
    existing_contact_email_keys: frozenset[str] = frozenset()
    """The keys (`normalize_email(...)[1]`) of the owner's contacts."""
    open_task_title_keys: frozenset[str] = frozenset()
    """`match_key(title)` of the owner's open tasks."""
    recorded_by_source: Mapping[str, int] | None = None
    """Suggestions this run already holds per source fingerprint."""


@dataclass(frozen=True, slots=True)
class Proposal:
    effect: str
    payload: object
    rationale: str
    datapoint_refs: Sequence[UUID] = ()


@dataclass(frozen=True, slots=True)
class Screened:
    """A proposal that was kept: validated, normalised and flagged."""

    index: int
    parsed: ParsedPayload
    rationale: str
    datapoint_ids: tuple[UUID, ...]
    flags: tuple[ScreeningFlag, ...]
    source_fingerprints: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class Rejection:
    index: int
    code: RejectionCode


@dataclass(frozen=True, slots=True)
class ScreeningResult:
    accepted: tuple[Screened, ...]
    rejected: tuple[Rejection, ...]


# --- patterns -----------------------------------------------------------------------------------

_LINK = re.compile(
    r"(?:\b[a-z][a-z0-9+.\-]{1,15}://|\bwww\.|\bmailto:|\bjavascript:|\bvbscript:|\bdata:[a-z]+/)",
    re.IGNORECASE,
)
_BARE_DOMAIN = re.compile(
    r"\b(?:[a-z0-9-]+\.)+(?:com|net|org|se|no|dk|fi|de|uk|io|co|info|biz|xyz|top|ru|cn|example"
    r"|app|dev|link|click|online|site|shop)\b",
    re.IGNORECASE,
)
_EMAIL_TOKEN = re.compile(r"\S+@\S+")
_HOSTISH = re.compile(r"(?:[\w-]+\.)+[\w-]{2,}")

_PAYMENT_WORDS = re.compile(
    r"\b(?:pay(?:ment|ments|ing)?|invoices?|invoiced|transfer|wire|iban|bic|swift|bankgiro"
    r"|plusgiro|swish|bank account|credit card|betal\w*|faktur\w*|överför\w*|bankkonto"
    r"|kontonummer|ocr)\b",
    re.IGNORECASE,
)
_IBAN = re.compile(r"\b[A-Z]{2}\d{2}(?: ?[A-Z0-9]{4}){2,7}(?: ?[A-Z0-9]{1,3})?\b", re.IGNORECASE)
_BANKGIRO = re.compile(r"\b(?!(?:19|20)\d{2}-(?:19|20)\d{2}\b)\d{3,4}-\d{4}\b")
_SWISH_NUMBER = re.compile(r"\b123[ -]?\d{3}[ -]?\d{2}[ -]?\d{2}\b")

_HIDDEN_CONTROLS = re.compile("[\u202a-\u202e\u2066-\u2069\U000e0000-\U000e007f]")
_INVISIBLE_SEPARATORS = re.compile("[\u00ad\u200b-\u200f\u2060\ufeff]")
_INSTRUCTION_PATTERNS = tuple(
    re.compile(pattern, re.IGNORECASE)
    for pattern in (
        r"\bignore\b.{0,40}\b(?:previous|prior|above|earlier|all)\b.{0,30}"
        r"\b(?:instructions?|prompts?|rules?|messages?)\b",
        r"\bdisregard\b.{0,40}\b(?:instructions?|rules?|prompts?|above|previous)\b",
        r"\b(?:system|assistant|developer)\s*:",
        r"[<\u2039]\s*/?\s*\|?\s*(?:tool_?call|tool_?use|function_?call|invoke|system|im_start)",
        r"\"(?:tool|function|name)\"\s*:\s*\"[\w.-]+\"\s*,\s*\"(?:arguments|parameters|input)\"",
        r"\byou are now\b",
        r"\bnew instructions?\b",
        r"\b(?:approve|accept|confirm)\s+(?:all|everything|these|this)\b",
        r"\bhigh[- ]confidence\b",
        r"\bconfidence\s*(?:of|is|=|:)?\s*\d{2,3}\b",
        r"\b\d{2,3}\s*%\s*confiden",
        r"\bnote to (?:the )?(?:reviewer|checker|system|assistant|ai|model)\b",
        r"\b(?:reviewer|checker)\b.{0,30}\b(?:safe|ok|approve)",
        r"\bmark (?:this |it )?as (?:safe|ok|approved|high)\b",
        r"\bdo not (?:tell|inform|mention)\b.{0,30}\b(?:user|owner)\b",
        r"\bignorera\b.{0,40}\b(?:tidigare|ovanstående|föregående)\b",
        r"\bbortse från\b",
        r"\bgodkänn (?:allt|alla)\b",
        r"display\s*:\s*none|visibility\s*:\s*hidden|font-size\s*:\s*0\b|opacity\s*:\s*0\b",
        r"\bcolor\s*:\s*(?:#fff(?:fff)?|white)\b",
    )
)
_BASE64_TOKEN = re.compile(r"[A-Za-z0-9+/]{24,}={0,2}")


# --- small helpers ------------------------------------------------------------------------------


def _domain_of(address: str) -> str:
    return address.rpartition("@")[2].strip().rstrip(".").casefold()


def email_matches_sender(email: str, sender_domains: Collection[str]) -> bool:
    """Whether the e-mail's domain is exactly one of the sender domains. False without any."""

    return _domain_of(email) in {domain.rstrip(".").casefold() for domain in sender_domains}


def _scripts(host: str) -> set[str]:
    scripts: set[str] = set()
    for character in host:
        if character.isalpha():
            scripts.add(unicodedata.name(character, "UNKNOWN").split(" ")[0])
    return scripts


def _decoded_host(host: str) -> str:
    if "xn--" not in host.casefold():
        return host
    try:
        return host.encode("ascii").decode("idna")
    except UnicodeError:
        return host


def _strings(value: object) -> Iterator[str]:
    """Every string inside a payload as it was sent, keys excluded."""

    if isinstance(value, str):
        yield value
    elif isinstance(value, Mapping):
        for item in cast(Mapping[object, object], value).values():
            yield from _strings(item)
    elif isinstance(value, Sequence):
        for item in cast(Sequence[object], value):
            yield from _strings(item)


# --- flag detectors -----------------------------------------------------------------------------


def _has_link(texts: Sequence[str]) -> bool:
    return any(
        _LINK.search(reading) or _BARE_DOMAIN.search(_EMAIL_TOKEN.sub(" ", reading))
        for text in texts
        for reading in detection_readings(text)
    )


def _is_payment_related(texts: Sequence[str]) -> bool:
    return any(
        pattern.search(reading)
        for text in texts
        for reading in detection_readings(text)
        for pattern in (_PAYMENT_WORDS, _IBAN, _BANKGIRO, _SWISH_NUMBER)
    )


def _has_mixed_script_domain(texts: Sequence[str], emails: Sequence[str]) -> bool:
    hosts = [_domain_of(email) for email in emails]
    hosts += [
        match.group(0)
        for text in texts
        for reading in decoded_readings(text)
        for match in _HOSTISH.finditer(reading)
    ]
    return any(len(_scripts(_decoded_host(host))) > 1 for host in hosts)


def _variants(text: str) -> Iterator[str]:
    """The text and the readings of it a model could be asked to follow: HTML and URL escapes
    undone (also twice), look-alike letters folded, rot13 and base64-decoded."""

    for reading in decoded_readings(text):
        for form in (reading, *folded_forms(reading)):
            yield form
            yield codecs.decode(form, "rot13")
        for token in _BASE64_TOKEN.findall(reading):
            decoded = _decode_base64_text(token)
            if decoded is not None:
                yield decoded
                yield from folded_forms(decoded)


def _decode_base64_text(token: str) -> str | None:
    try:
        raw = base64.b64decode(token + "=" * (-len(token) % 4), validate=True)
        text = raw.decode("utf-8")
    except (binascii.Error, UnicodeDecodeError):
        return None
    printable = sum(character.isprintable() for character in text)
    return text if len(text) >= 16 and " " in text and printable >= 0.9 * len(text) else None


def _is_hidden_or_encoded(raw: str) -> bool:
    """Text that hides itself: bidirectional overrides, tag characters or readable base64."""

    if _HIDDEN_CONTROLS.search(raw):
        return True
    return any(_decode_base64_text(token) is not None for token in _BASE64_TOKEN.findall(raw))


def _is_instruction_like(raw_texts: Sequence[str]) -> bool:
    for raw in raw_texts:
        if _is_hidden_or_encoded(raw):
            return True
        for reading in (clean_text(raw), _INVISIBLE_SEPARATORS.sub(" ", raw)):
            for variant in _variants(reading):
                if any(pattern.search(variant) for pattern in _INSTRUCTION_PATTERNS):
                    return True
    return False


def _unverified_contact(parsed: ParsedPayload, sources: Sequence[SourceInfo]) -> bool:
    email = contact_email(parsed)
    mail_domains = {
        source.sender_domain
        for source in sources
        if source.kind == "mail" and source.sender_domain is not None
    }
    return bool(email and mail_domains and not email_matches_sender(email, mail_domains))


def _duplicates_existing(parsed: ParsedPayload, context: ScreeningContext) -> bool:
    email = contact_email(parsed)
    if email is not None:
        return (normalize_email(email)[1] or "") in context.existing_contact_email_keys
    if isinstance(parsed.value, CreateTaskV1):
        return match_key(parsed.value.title) in context.open_task_title_keys
    return False


_TEXT_FLAGS = frozenset(
    {
        ScreeningFlag.CONTAINS_LINK,
        ScreeningFlag.PAYMENT_RELATED,
        ScreeningFlag.HOMOGLYPH_DOMAIN,
        ScreeningFlag.INSTRUCTION_LIKE_TEXT,
    }
)
"""The flags that read text, from the payload or from the rationale."""


def _ordered(flags: Collection[ScreeningFlag]) -> tuple[ScreeningFlag, ...]:
    return tuple(flag for flag in ScreeningFlag if flag in flags)


def _text_flags(
    texts: Sequence[str], emails: Sequence[str], raw_texts: Sequence[str]
) -> frozenset[ScreeningFlag]:
    checks = (
        (ScreeningFlag.CONTAINS_LINK, _has_link(texts)),
        (ScreeningFlag.PAYMENT_RELATED, _is_payment_related(texts)),
        (ScreeningFlag.HOMOGLYPH_DOMAIN, _has_mixed_script_domain(texts, emails)),
        (ScreeningFlag.INSTRUCTION_LIKE_TEXT, _is_instruction_like(raw_texts)),
    )
    return frozenset(flag for flag, found in checks if found)


def _flags_for(
    parsed: ParsedPayload,
    rationale: str,
    raw_texts: Sequence[str],
    sources: Sequence[SourceInfo],
    context: ScreeningContext,
) -> tuple[ScreeningFlag, ...]:
    texts = [*free_text(parsed), rationale]
    emails = [email] if (email := contact_email(parsed)) else []
    found = _text_flags(texts, emails, raw_texts)
    if _unverified_contact(parsed, sources):
        found |= {ScreeningFlag.CONTACT_DETAIL_UNVERIFIED}
    if _duplicates_existing(parsed, context):
        found |= {ScreeningFlag.DUPLICATE_EXISTING}
    return _ordered(found)


def flags_for_edit(
    parsed: ParsedPayload,
    rationale: str,
    raw_payload: object,
    sources: Sequence[SourceInfo],
    context: ScreeningContext,
) -> tuple[ScreeningFlag, ...]:
    """The flags of a payload the owner edited, from the same detectors as a new proposal.

    The rationale is read too, as it is stored. What the card carried before the edit is
    `flags_after_edit`'s to keep."""

    return _flags_for(parsed, rationale, [*_strings(raw_payload), rationale], sources, context)


def flags_after_edit(
    previous_flags: Collection[ScreeningFlag],
    previous_payload: object,
    rationale: str,
    edited_flags: Collection[ScreeningFlag],
) -> tuple[ScreeningFlag, ...]:
    """The flags a card holds after an edit: `edited_flags` (see `flags_for_edit`) and every earlier
    flag that did not come from payload text the owner may have changed.

    A flag comes from the payload when the previous payload's own text raises it and the rationale
    alone does not; an edit that removes that text clears it. Everything else stays: a flag from the
    rationale, from the source (`large_batch`) or one that the stored text no longer explains (text
    that hid itself and was stripped). A flag can therefore only disappear because the owner
    changed the payload text that caused it.
    """

    previous_texts = list(_strings(previous_payload))
    from_payload = _text_flags(previous_texts, (), previous_texts) - _text_flags(
        [rationale], (), [rationale]
    )
    kept = {
        flag
        for flag in previous_flags
        if flag not in from_payload
        and flag not in (ScreeningFlag.CONTACT_DETAIL_UNVERIFIED, ScreeningFlag.DUPLICATE_EXISTING)
    }
    return _ordered({*kept, *edited_flags})


# --- screening one call -------------------------------------------------------------------------


def _refuse_before_parsing(
    proposal: Proposal, context: ScreeningContext
) -> tuple[EffectKind | None, RejectionCode | None]:
    kind = resolve_effect(proposal.effect)
    if kind is None:
        return None, RejectionCode.EFFECT_UNKNOWN
    if kind not in context.allowed_effects:
        return None, RejectionCode.EFFECT_NOT_ALLOWED
    return kind, None


def _clean_rationale(value: str) -> str | RejectionCode:
    rationale = normalise_line(value)
    if not rationale:
        return RejectionCode.SCHEMA_INVALID
    if len(rationale) > MAX_RATIONALE_CHARS:
        return RejectionCode.TOO_LONG
    return rationale


def _check_references(
    proposal: Proposal, parsed: ParsedPayload, context: ScreeningContext
) -> RejectionCode | None:
    if len(proposal.datapoint_refs) > MAX_DATAPOINT_REFS:
        return RejectionCode.TOO_LONG
    if any(ref not in context.datapoint_sources for ref in proposal.datapoint_refs):
        return RejectionCode.DATAPOINT_NOT_IN_RUN
    project_id = project_reference(parsed)
    if project_id is not None and project_id not in context.usable_project_ids:
        return RejectionCode.REFERENCE_UNUSABLE
    return None


def _screen_one(index: int, proposal: Proposal, context: ScreeningContext) -> Screened | Rejection:
    kind, refusal = _refuse_before_parsing(proposal, context)
    if kind is None or refusal is not None:
        return Rejection(index, refusal or RejectionCode.EFFECT_UNKNOWN)
    parsed = parse_payload(kind, proposal.payload)
    if isinstance(parsed, PayloadProblem):
        return Rejection(index, RejectionCode(parsed.value))
    rationale = _clean_rationale(proposal.rationale)
    if isinstance(rationale, RejectionCode):
        return Rejection(index, rationale)
    reference_problem = _check_references(proposal, parsed, context)
    if reference_problem is not None:
        return Rejection(index, reference_problem)
    datapoint_ids = tuple(dict.fromkeys(proposal.datapoint_refs))
    sources = [context.datapoint_sources[ref] for ref in datapoint_ids]
    raw_texts = [*_strings(proposal.payload), proposal.rationale]
    return Screened(
        index=index,
        parsed=parsed,
        rationale=rationale,
        datapoint_ids=datapoint_ids,
        flags=_flags_for(parsed, rationale, raw_texts, sources, context),
        source_fingerprints=tuple(sorted({source.fingerprint for source in sources})),
    )


def _flag_large_batches(
    accepted: Sequence[Screened], recorded_by_source: Mapping[str, int] | None
) -> tuple[Screened, ...]:
    counts: Counter[str] = Counter(dict(recorded_by_source or {}))
    for item in accepted:
        counts.update(item.source_fingerprints)
    flagged: list[Screened] = []
    for item in accepted:
        large = any(counts[source] > LARGE_BATCH_LIMIT for source in item.source_fingerprints)
        if large and ScreeningFlag.LARGE_BATCH not in item.flags:
            item = replace(item, flags=(*item.flags, ScreeningFlag.LARGE_BATCH))
        flagged.append(item)
    return tuple(flagged)


def screen_proposals(proposals: Sequence[Proposal], context: ScreeningContext) -> ScreeningResult:
    """Screen one call's proposals: each is kept (normalised, flagged) or refused with a code.

    Nothing is raised for a bad proposal: every index is answered. When the run is not open every
    proposal is refused. Proposals beyond the run's remaining cap are refused in order.
    """

    if not context.run_open:
        return ScreeningResult(
            (), tuple(Rejection(i, RejectionCode.RUN_NOT_RUNNING) for i, _ in enumerate(proposals))
        )
    room = max(context.max_suggestions - context.already_recorded, 0)
    accepted: list[Screened] = []
    rejected: list[Rejection] = []
    for index, proposal in enumerate(proposals):
        if len(accepted) >= room:
            rejected.append(Rejection(index, RejectionCode.OVER_RUN_CAP))
            continue
        outcome = _screen_one(index, proposal, context)
        if isinstance(outcome, Rejection):
            rejected.append(outcome)
        else:
            accepted.append(outcome)
    return ScreeningResult(
        _flag_large_batches(accepted, context.recorded_by_source), tuple(rejected)
    )
