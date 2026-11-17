"""The Slack profile link of a Contact: what is accepted, how it is normalized, how it clears."""

from datetime import UTC, datetime
from uuid import UUID

import pytest

from sidekick.contacts.application.models import UpdateContactCommand
from sidekick.contacts.domain.contact import Contact
from sidekick.contacts.domain.normalization import normalize_slack_profile
from sidekick.shared.errors import ValidationError
from sidekick.shared.types import UNSET

NOW = datetime(2026, 11, 17, 12, 0, tzinfo=UTC)
CANONICAL = "https://acme.slack.com/team/U01ABC23DEF"


def make_contact() -> Contact:
    return Contact(
        id=UUID(int=1),
        owner_id=UUID(int=2),
        display_name="Anna",
        display_name_key="anna",
        context_note=None,
        email=None,
        email_key=None,
        phone=None,
        phone_key=None,
        aliases=[],
        archived=False,
        created_at=NOW,
        updated_at=NOW,
        archived_at=None,
    )


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (CANONICAL, CANONICAL),
        ("  https://acme.slack.com/team/U01ABC23DEF  ", CANONICAL),
        ("HTTPS://ACME.Slack.com/team/U01ABC23DEF", CANONICAL),
        ("https://acme.slack.com/team/U01ABC23DEF/", CANONICAL),
        ("https://acme.slack.com/team/U01ABC23DEF?utm=1#top", CANONICAL),
        ("acme.slack.com/team/U01ABC23DEF", CANONICAL),
        (
            "https://acme.enterprise.slack.com/team/W0ABC12345",
            "https://acme.enterprise.slack.com/team/W0ABC12345",
        ),
        ("https://my-team-2.slack.com/team/UABC", "https://my-team-2.slack.com/team/UABC"),
    ],
)
def test_a_profile_link_is_normalized_to_its_canonical_form(value: str, expected: str) -> None:
    assert normalize_slack_profile(value) == expected


@pytest.mark.parametrize("value", [None, "", "   "])
def test_a_blank_value_clears_the_link(value: str | None) -> None:
    assert normalize_slack_profile(value) is None


@pytest.mark.parametrize(
    "value",
    [
        "http://acme.slack.com/team/U01ABC23DEF",
        "javascript:alert(1)",
        "slack://user?team=T01&id=U01ABC23DEF",
        "ftp://acme.slack.com/team/U01ABC23DEF",
        "https://slack.com/team/U01ABC23DEF",
        "https://evil.com/team/U01ABC23DEF",
        "https://acme.slack.com.evil.com/team/U01ABC23DEF",
        "https://notslack.com/team/U01ABC23DEF",
        "https://evilslack.com/team/U01ABC23DEF",
        "https://acme.slack.com@evil.com/team/U01ABC23DEF",
        "https://user:pw@acme.slack.com/team/U01ABC23DEF",
        "https://acme.slack.com:8443/team/U01ABC23DEF",
        "https://acme.slack.com/team/u01abc23def",
        "https://acme.slack.com/team/X01ABC23DEF",
        "https://acme.slack.com/team/U1",
        "https://acme.slack.com/team/",
        "https://acme.slack.com/team/U01ABC23DEF/extra",
        "https://acme.slack.com/archives/U01ABC23DEF",
        "https://acme.slack.com/",
        "https://acme.slack.com",
        "https://acme.slack.com/team/U01ABC23DEF\nhttps://evil.com",
        "https://acme.slack.com/team/U01ABC23DEF evil",
        "https://äcme.slack.com/team/U01ABC23DEF",
        "https://-acme.slack.com/team/U01ABC23DEF",
        "U01ABC23DEF",
        "https://acme.slack.com/team/U01ABC23DEF" + "x" * 300,
    ],
)
def test_anything_but_a_slack_profile_link_is_refused(value: str) -> None:
    with pytest.raises(ValidationError):
        normalize_slack_profile(value)


def test_update_sets_and_clears_the_slack_link() -> None:
    contact = make_contact()
    linked = contact.update(now=NOW, slack="acme.slack.com/team/U01ABC23DEF")
    assert linked.slack == CANONICAL
    assert linked.version == contact.version + 1
    # A field left out stays as it was; a blank value clears it.
    assert linked.update(now=NOW, display_name="Anna Lind").slack == CANONICAL
    assert linked.update(now=NOW, slack="").slack is None
    with pytest.raises(ValidationError):
        linked.update(now=NOW, slack="https://evil.com/team/U01ABC23DEF")


def test_the_update_command_reports_slack_only_when_it_was_set() -> None:
    assert UpdateContactCommand(display_name="Anna").changes() == {"display_name": "Anna"}
    assert UpdateContactCommand(slack=CANONICAL).changes() == {"slack": CANONICAL}
    assert UpdateContactCommand().slack is UNSET
