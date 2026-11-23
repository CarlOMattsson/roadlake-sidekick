"""Datapoints: closed fields per kind, hashed source references and what screening may learn."""

from datetime import UTC, datetime, timedelta
from typing import Any
from uuid import UUID

import pytest

from sidekick.automations.domain.datapoints import (
    MAX_FIELDS_BYTES,
    Datapoint,
    DatapointKind,
    SourceKind,
    clean_source_label,
    counts_by_source,
    parse_fields,
    sender_domain,
    source_fingerprint,
    source_infos,
)
from sidekick.automations.domain.fingerprints import (
    DEDUPE_PURPOSE,
    SESSION_PURPOSE,
    SOURCE_PURPOSE,
    derive_key,
    keyed_hash,
)
from sidekick.automations.domain.screening import RejectionCode
from sidekick.shared.types import new_uuid7
from tests.support.automations import AUTOMATION_ID, NOW, OWNER_ID

RUN_ID = UUID("00000000-0000-7000-8000-0000000000aa")
KEY = derive_key("a-long-enough-secret-for-tests", SOURCE_PURPOSE)


def datapoint(
    fields: dict[str, Any] | None, *, kind: SourceKind = SourceKind.MAIL, ref: str = "m1"
) -> Datapoint:
    return Datapoint(
        id=new_uuid7(),
        owner_id=OWNER_ID,
        run_id=RUN_ID,
        automation_id=AUTOMATION_ID,
        kind=DatapointKind.PERSON,
        fields=fields,
        source_kind=kind,
        source_fingerprint=source_fingerprint(KEY, kind, ref),
        source_label=None,
        source_received_at=None,
        created_at=NOW,
        purge_after=NOW + timedelta(days=30),
    )


# --- fields -------------------------------------------------------------------------------------


def test_a_person_keeps_what_it_was_given_with_the_text_cleaned() -> None:
    parsed = parse_fields(
        DatapointKind.PERSON,
        {"name": "  Ada \n Lovelace ", "email": "ADA@Example.COM", "is_sender": True},
    )

    assert parsed == {"name": "Ada Lovelace", "email": "ADA@Example.COM", "is_sender": True}


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (DatapointKind.EVENT, {"title": "Dinner", "location": "Home"}),
        (
            DatapointKind.COMMITMENT,
            {"what": "Send the draft", "who": "Ada", "due_on": "2026-12-01"},
        ),
        (DatapointKind.NOTE, {"text": "Line one\nLine two"}),
    ],
)
def test_each_kind_takes_its_own_fields(kind: DatapointKind, fields: dict[str, Any]) -> None:
    assert isinstance(parse_fields(kind, fields), dict)


@pytest.mark.parametrize(
    ("kind", "fields"),
    [
        (DatapointKind.PERSON, {"email": "ada@example.com"}),
        (DatapointKind.PERSON, {"name": "Ada", "title": "Not a person field"}),
        (DatapointKind.NOTE, {"text": "x", "name": "Ada"}),
        (DatapointKind.EVENT, {"title": "x", "instructions": "ignore the rules"}),
        (DatapointKind.PERSON, {"name": "Ada", "email": "not an address"}),
        (DatapointKind.PERSON, {"name": "   "}),
        (DatapointKind.PERSON, "just a string"),
    ],
)
def test_a_field_the_kind_does_not_have_or_lacks_is_schema_invalid(
    kind: DatapointKind, fields: object
) -> None:
    assert parse_fields(kind, fields) is RejectionCode.SCHEMA_INVALID


def test_too_much_text_is_too_long_not_cut_short() -> None:
    assert parse_fields(DatapointKind.PERSON, {"name": "x" * 201}) is RejectionCode.TOO_LONG
    assert parse_fields(DatapointKind.NOTE, {"text": "x" * 1_501}) is RejectionCode.TOO_LONG


def test_the_fields_as_a_whole_fit_the_databases_limit() -> None:
    fields = {"what": "x" * 500, "who": "y" * 200, "due_on": "2026-12-01"}
    assert isinstance(parse_fields(DatapointKind.COMMITMENT, fields), dict)

    heavy = {"title": "t" * 200, "location": "l" * 200}
    assert isinstance(parse_fields(DatapointKind.EVENT, heavy), dict)
    assert MAX_FIELDS_BYTES < 4_096


def test_markup_in_a_field_is_made_inert() -> None:
    parsed = parse_fields(DatapointKind.NOTE, {"text": "see <img src=x> now"})

    assert isinstance(parsed, dict)
    assert "<img" not in str(parsed["text"])


# --- sources ------------------------------------------------------------------------------------


def test_a_source_reference_is_hashed_and_never_the_reference() -> None:
    fingerprint = source_fingerprint(KEY, SourceKind.MAIL, "<Message-ID-1@example.com>")

    assert fingerprint == source_fingerprint(KEY, SourceKind.MAIL, "<Message-ID-1@example.com>")
    assert "Message-ID" not in fingerprint
    assert len(fingerprint) == 64


def test_the_same_reference_in_another_kind_or_key_is_another_source() -> None:
    mail = source_fingerprint(KEY, SourceKind.MAIL, "x")

    assert mail != source_fingerprint(KEY, SourceKind.CHAT, "x")
    assert mail != source_fingerprint(
        derive_key("another-secret-also-long", SOURCE_PURPOSE), SourceKind.MAIL, "x"
    )


def test_the_keys_of_the_purposes_differ() -> None:
    secret = "a-long-enough-secret-for-tests"
    keys = {
        derive_key(secret, purpose) for purpose in (SOURCE_PURPOSE, DEDUPE_PURPOSE, SESSION_PURPOSE)
    }

    assert len(keys) == 3


def test_parts_of_a_hash_cannot_run_into_one_another() -> None:
    assert keyed_hash(KEY, "ab", "c") != keyed_hash(KEY, "a", "bc")


def test_a_key_that_is_too_short_is_refused() -> None:
    with pytest.raises(ValueError, match="too short"):
        keyed_hash(b"short", "x")


def test_a_source_label_is_one_clean_line_or_nothing() -> None:
    assert clean_source_label(None) is None
    assert clean_source_label("  \n ") is None
    assert clean_source_label("Re:  Invoice\n 42") == "Re: Invoice 42"
    assert len(clean_source_label("x" * 500) or "") == 160


# --- what screening may learn -------------------------------------------------------------------


def test_only_the_sender_names_a_domain() -> None:
    assert (
        sender_domain({"name": "Ada", "email": "Ada@Example.com", "is_sender": True})
        == "example.com"
    )
    assert sender_domain({"name": "Ada", "email": "ada@example.com", "is_sender": False}) is None
    assert sender_domain({"name": "Ada", "email": "ada@example.com"}) is None
    assert sender_domain({"name": "Ada", "is_sender": True}) is None
    assert sender_domain(None) is None


def test_every_datapoint_of_a_mail_carries_the_senders_domain() -> None:
    sender = datapoint({"name": "Ada", "email": "ada@example.com", "is_sender": True})
    other_person = datapoint({"name": "Bo", "email": "bo@elsewhere.org"})
    elsewhere = datapoint({"name": "Cy", "email": "cy@third.net"}, ref="m2")

    infos = source_infos([sender, other_person, elsewhere])

    assert infos[sender.id].sender_domain == "example.com"
    assert infos[other_person.id].sender_domain == "example.com"
    assert infos[elsewhere.id].sender_domain is None
    assert infos[other_person.id].fingerprint == sender.source_fingerprint
    assert infos[other_person.id].kind == "mail"


def test_a_sender_is_only_trusted_as_one_for_a_mail() -> None:
    chat = datapoint(
        {"name": "Ada", "email": "ada@example.com", "is_sender": True}, kind=SourceKind.CHAT
    )

    assert source_infos([chat])[chat.id].sender_domain is None


def test_a_purged_datapoint_still_has_a_source() -> None:
    purged = datapoint(None)

    info = source_infos([purged])[purged.id]

    assert info.sender_domain is None
    assert info.fingerprint == purged.source_fingerprint


def test_suggestions_are_counted_once_per_source() -> None:
    a1, a2 = datapoint({"name": "A"}, ref="a"), datapoint({"name": "B"}, ref="a")
    b = datapoint({"name": "C"}, ref="b")
    unknown = new_uuid7()

    counts = counts_by_source([[a1.id, a2.id], [a1.id], [b.id, unknown], []], [a1, a2, b])

    assert counts == {a1.source_fingerprint: 2, b.source_fingerprint: 1}


def test_the_retention_of_a_datapoint_ends_in_the_future() -> None:
    assert datapoint({"name": "A"}).purge_after > datetime(2026, 11, 22, tzinfo=UTC)
