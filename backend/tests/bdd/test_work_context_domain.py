from datetime import UTC, datetime
from uuid import uuid4

import pytest

from sidekick.shared.errors import ValidationError
from sidekick.work.domain import Domain, DomainStatus, Process, ProcessStatus
from sidekick.work.domain.context import DOMAIN_ACCENTS


def test_domain_normalizes_name_and_updates_version() -> None:
    now = datetime.now(UTC)
    domain = Domain(uuid4(), uuid4(), "  Personal  ", None, DomainStatus.ACTIVE, now, now)
    updated = domain.update(now=now, name="Home")
    assert updated.name == "Home"
    assert updated.version == 2


def test_process_requires_domain_and_has_peer_lifecycle() -> None:
    now = datetime.now(UTC)
    process = Process(
        uuid4(), uuid4(), uuid4(), "Weekly review", None, ProcessStatus.ACTIVE, now, now
    )
    assert process.domain_id
    assert process.update(now=now, status=ProcessStatus.PAUSED).version == 2


@pytest.mark.parametrize("name", ["", "   ", "x" * 201])
def test_context_names_are_bounded(name: str) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Domain(uuid4(), uuid4(), name, None, DomainStatus.ACTIVE, now, now)


def test_domain_accent_defaults_to_none_and_the_palette_is_closed() -> None:
    now = datetime.now(UTC)
    domain = Domain(uuid4(), uuid4(), "Home", None, DomainStatus.ACTIVE, now, now)
    assert domain.accent is None
    assert DOMAIN_ACCENTS == (
        "slate",
        "blue",
        "teal",
        "green",
        "amber",
        "orange",
        "rose",
        "violet",
    )


@pytest.mark.parametrize("accent", DOMAIN_ACCENTS)
def test_domain_accepts_each_palette_name(accent: str) -> None:
    now = datetime.now(UTC)
    domain = Domain(uuid4(), uuid4(), "Home", None, DomainStatus.ACTIVE, now, now, accent=accent)
    assert domain.accent == accent


@pytest.mark.parametrize("accent", ["", "red", "VIOLET", " blue", "#3366ff", "slate;"])
def test_domain_rejects_unknown_accent_names(accent: str) -> None:
    now = datetime.now(UTC)
    with pytest.raises(ValidationError):
        Domain(uuid4(), uuid4(), "Home", None, DomainStatus.ACTIVE, now, now, accent=accent)


def test_domain_update_sets_and_clears_accent() -> None:
    now = datetime.now(UTC)
    domain = Domain(uuid4(), uuid4(), "Home", None, DomainStatus.ACTIVE, now, now)
    coloured = domain.update(now=now, accent="teal")
    assert coloured.accent == "teal"
    assert coloured.version == 2
    cleared = coloured.update(now=now, accent=None)
    assert cleared.accent is None
    assert cleared.version == 3
    # An update that does not mention accent keeps the stored colour.
    renamed = coloured.update(now=now, name="Hem")
    assert renamed.accent == "teal"


def test_domain_update_rejects_unknown_accent() -> None:
    now = datetime.now(UTC)
    domain = Domain(uuid4(), uuid4(), "Home", None, DomainStatus.ACTIVE, now, now)
    with pytest.raises(ValidationError):
        domain.update(now=now, accent="neon")
