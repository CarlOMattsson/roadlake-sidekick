"""External reference rules without a framework or database."""

from datetime import UTC, datetime

import pytest

from sidekick.references.domain import (
    ExternalReferenceDetails,
    validate_reference_url,
)
from sidekick.shared.errors import ValidationError


def details(**overrides: object) -> ExternalReferenceDetails:
    values: dict[str, object] = {
        "kind": "mail",
        "provider": "google_gmail",
        "account_ref": "Owner@Example.com",
        "external_id": "thread-123",
        "title": "Offert från leverantören",
        "url": "https://mail.google.com/mail/u/0/#inbox/thread-123",
    }
    values.update(overrides)
    return ExternalReferenceDetails(**values)  # type: ignore[arg-type]


def test_valid_reference_normalizes_account_and_keeps_fragment() -> None:
    reference = details()
    assert reference.account_ref == "owner@example.com"
    assert reference.url == "https://mail.google.com/mail/u/0/#inbox/thread-123"
    assert reference.instance_ref is None


@pytest.mark.parametrize(
    ("provider", "url"),
    [
        ("google_gmail", "https://mail.google.com/mail/u/0/#all/abc"),
        ("google_calendar", "https://calendar.google.com/calendar/event?eid=abc"),
        ("google_drive", "https://docs.google.com/document/d/abc/edit"),
        ("google_drive", "https://drive.google.com/file/d/abc/view"),
        ("other", "https://example.org/anything?q=1#frag"),
        ("other", "https://example.org:443/path"),
        ("google_drive", "https://docs.google.com/document/d/abc/edit?usp=sharing"),
    ],
)
def test_allowed_links(provider: str, url: str) -> None:
    assert validate_reference_url(provider, url) == url


def test_uppercase_scheme_and_host_are_normalized_to_match_the_database_check() -> None:
    assert (
        validate_reference_url("google_drive", "HTTPS://Docs.Google.COM/document/d/Abc/edit")
        == "https://docs.google.com/document/d/Abc/edit"
    )
    assert (
        validate_reference_url("other", "HTTPS://EXAMPLE.org:443/Path?Q=1#Frag")
        == "https://example.org:443/Path?Q=1#Frag"
    )
    reference = details(url="HTTPS://Mail.Google.com/mail/u/0/#inbox/thread-123")
    assert reference.url == "https://mail.google.com/mail/u/0/#inbox/thread-123"


@pytest.mark.parametrize(
    "url",
    [
        "https://example.org/x#access_token=x",
        "https://example.org/x#frag&token=x",
        "https://example.org/?api_key=x",
        "https://example.org/?client_secret=x",
        "https://example.org/?X-Goog-Signature=x",
        "https://example.org/?password=x",
        "https://example.org/?sessionid=x",
        "https://example.org/?JWT=x",
        "https://example.org/?refresh_token=x",
        "https://example.org/?my_api_key=x",
        "https://example.org/?db_password=x",
        "https://example.org/?X-Goog-Credential=x",
    ],
)
def test_credential_parameters_are_refused_in_query_and_fragment(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_reference_url("other", url)


@pytest.mark.parametrize(
    "url",
    [
        "https://docs.google.com/document/d/design/edit?authuser=0",
        "https://docs.google.com/document/d/abc/edit?resourcekey=x",
        "https://docs.google.com/document/d/abc/edit?usp=sharing",
    ],
)
def test_common_google_parameters_are_allowed(url: str) -> None:
    assert validate_reference_url("google_drive", url) == url


def test_fragment_without_equals_is_not_parsed_as_parameters() -> None:
    assert (
        validate_reference_url("google_gmail", "https://mail.google.com/mail/u/0/#inbox/token")
        == "https://mail.google.com/mail/u/0/#inbox/token"
    )


@pytest.mark.parametrize(
    "url",
    [
        "http://mail.google.com/x",
        "javascript:alert(1)",
        "data:text/html,<script>1</script>",
        "file:///etc/passwd",
        "intent://scan/#Intent;scheme=zxing;end",
        "mycustom://open/1",
        "//mail.google.com/x",
        "https://user:pass@mail.google.com/x",
        "https://user@mail.google.com/x",
        "https://mail.google.com:8443/x",
        "https://mail.google.com\\@evil.example/x",
        "https://mail.google.com/x\ny",
        "https://mail.google.com/a b",
        "https://mail.google.com/\x00",
        "https://evil.example/x",
        "https://mail.google.com.evil.example/x",
        "https://calendar.google.com/x",
        "https:///nohost",
        "",
    ],
)
def test_forbidden_links_for_a_gmail_reference(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_reference_url("google_gmail", url)


@pytest.mark.parametrize(
    "url",
    [
        "http://example.org/x",
        "javascript:alert(1)",
        "data:text/plain,hi",
        "file:///etc/passwd",
        "https://user:pw@example.org/x",
        "https://example.org/x\\y",
        "https://example.org/?access_token=abc",
        "https://example.org/?Token=abc",
        "https://example.org/?a=1&sig=abc",
        "https://example.org/?X-Amz-Signature=abc",
        "https://example.org/?key=abc",
        "https://" + "a" * 2000,
    ],
)
def test_other_provider_still_refuses_unsafe_links(url: str) -> None:
    with pytest.raises(ValidationError):
        validate_reference_url("other", url)


def test_unknown_provider_is_refused() -> None:
    with pytest.raises(ValidationError):
        validate_reference_url("microsoft_graph", "https://outlook.office.com/x")
    with pytest.raises(ValidationError):
        details(provider="microsoft_graph")


def test_kind_must_fit_the_provider() -> None:
    with pytest.raises(ValidationError):
        details(kind="calendar_event")  # Gmail provider with a calendar kind
    with pytest.raises(ValidationError):
        details(kind="spreadsheet")
    assert details(kind="document", provider="other", url=None).provider == "other"


@pytest.mark.parametrize(
    "field",
    ["account_ref", "external_id", "title"],
)
def test_required_text_is_bounded_and_clean(field: str) -> None:
    with pytest.raises(ValidationError):
        details(**{field: "   "})
    with pytest.raises(ValidationError):
        details(**{field: "x" * 501})
    with pytest.raises(ValidationError):
        details(**{field: "bad\x00value"})


def test_title_limit_is_300() -> None:
    assert details(title="t" * 300).title == "t" * 300
    with pytest.raises(ValidationError):
        details(title="t" * 301)


def test_occurrence_needs_a_timezone() -> None:
    with pytest.raises(ValidationError):
        details(occurs_at=datetime(2026, 10, 25, 12, 0))
    assert details(occurs_at=datetime(2026, 10, 25, 12, 0, tzinfo=UTC)).occurs_at is not None


def test_identity_separates_accounts_and_instances_and_ignores_snapshot_text() -> None:
    base = details()
    assert base.identity == details(title="Ny rubrik", url=None).identity
    assert base.identity != details(account_ref="other@example.com").identity
    series = details(
        kind="calendar_event", provider="google_calendar", url=None, external_id="series-1"
    )
    occurrence = details(
        kind="calendar_event",
        provider="google_calendar",
        url=None,
        external_id="series-1",
        instance_ref="2026-11-01",
    )
    assert series.identity != occurrence.identity
    assert series.identity_fingerprint() != occurrence.identity_fingerprint()
    assert (
        base.identity_fingerprint()
        == details(account_ref="OWNER@example.com").identity_fingerprint()
    )
