"""One rule for a private destination, checked in both places that used to disagree.

The defect this closes was concrete: `Settings` accepted `http://127.0.0.1:18888` in the
(since retired) desktop mode, and `HindsightMemoryProvider` then raised on the same string,
because each held its own copy of the rule and only one had the exemption. These tests assert
the rule and, more importantly, that configuration and the adapter now answer identically.
"""

import pytest

from sidekick.memory.adapters.hindsight import HindsightMemoryProvider
from sidekick.shared.config import Settings
from sidekick.shared.private_endpoint import private_host, validate_private_base_url

TOKEN = "hindsight-test-token"
DERIVATION_KEY = "hindsight-derivation-secret"


def _provider(base_url: str, **kwargs: object) -> HindsightMemoryProvider:
    return HindsightMemoryProvider(
        base_url=base_url,
        api_token=TOKEN,
        id_derivation_key=DERIVATION_KEY,
        **kwargs,  # type: ignore[arg-type]
    )


def _hindsight_settings(
    base_url: str, environment: str = "development", **fields: object
) -> Settings:
    return Settings(
        _env_file=None,
        environment=environment,  # type: ignore[arg-type]
        cursor_signing_secret="x" * 48,
        token_pepper="y" * 48,
        memory_hindsight_base_url=base_url,
        **fields,  # type: ignore[arg-type]
    )


@pytest.mark.parametrize(
    ("host", "private"),
    [
        ("hindsight", True),
        ("HINDSIGHT.", True),
        ("memory.internal", True),
        ("box.local", True),
        ("10.1.2.3", True),
        ("172.16.0.9", True),
        ("192.168.0.5", True),
        ("memory.example.com", False),
        ("8.8.8.8", False),
        ("", False),
    ],
)
def test_private_host_classification_is_independent_of_the_loopback_exemption(
    host: str, private: bool
) -> None:
    assert private_host(host) is private
    assert private_host(host, allow_loopback=True) is private


@pytest.mark.parametrize("host", ["127.0.0.1", "127.0.0.53", "::1"])
def test_loopback_is_private_only_under_the_exemption(host: str) -> None:
    assert private_host(host) is False
    assert private_host(host, allow_loopback=True) is True


@pytest.mark.parametrize("host", ["0.0.0.0", "::"])
def test_unspecified_address_is_loopback_class(host: str) -> None:
    """0.0.0.0 and :: reach the local host, so they follow the loopback rule, not private."""

    assert private_host(host) is False
    assert private_host(host, allow_loopback=True) is True


@pytest.mark.parametrize(
    "host",
    [
        "169.254.169.254",
        "169.254.0.1",
        "fe80::1",
        "fe80::1%eth0",
        "::ffff:169.254.169.254",
    ],
)
def test_link_local_metadata_range_is_refused_even_under_the_exemption(host: str) -> None:
    assert private_host(host) is False
    assert private_host(host, allow_loopback=True) is False


def test_link_local_is_refused_through_validation_in_every_mode() -> None:
    with pytest.raises(ValueError, match="approved private host"):
        validate_private_base_url("http://169.254.169.254", label="Memory")
    with pytest.raises(ValueError, match="approved private host"):
        validate_private_base_url("http://169.254.169.254", allow_loopback=True)
    with pytest.raises(ValueError, match="approved private host"):
        validate_private_base_url("http://[fe80::1]:8888", allow_loopback=True)


@pytest.mark.parametrize("value", ["http://0.0.0.0:8888", "http://[::]:8888"])
def test_unspecified_destination_is_refused_without_the_exemption(value: str) -> None:
    with pytest.raises(ValueError, match="approved private host"):
        validate_private_base_url(value)
    assert validate_private_base_url(value, allow_loopback=True) == value


@pytest.mark.parametrize(
    ("value", "message"),
    [
        ("ftp://hindsight:8888", "HTTP\\(S\\) with a host"),
        ("hindsight:8888", "HTTP\\(S\\) with a host"),
        ("http://user:secret@hindsight:8888", "credentials or a path"),
        ("http://hindsight:8888/v1", "credentials or a path"),
        ("http://hindsight:8888?x=1", "query or fragment"),
        ("http://hindsight:8888#f", "query or fragment"),
        ("https://memory.example.com", "approved private host"),
    ],
)
def test_rejected_destinations_state_the_reason(value: str, message: str) -> None:
    with pytest.raises(ValueError, match=message):
        validate_private_base_url(value)
    with pytest.raises(ValueError, match=message):
        validate_private_base_url(value, allow_loopback=True)


def test_an_accepted_destination_loses_its_trailing_slash() -> None:
    assert validate_private_base_url("http://hindsight:8888/") == "http://hindsight:8888"


def test_the_label_names_the_service_in_the_message() -> None:
    with pytest.raises(ValueError, match="Memory base URL must target an approved private host"):
        validate_private_base_url("https://memory.example.com", label="Memory")


def test_the_adapter_refuses_loopback_without_the_exemption() -> None:
    """The old defect, kept as a test: this is what development mode has to opt out of."""

    with pytest.raises(ValueError, match="approved private host"):
        _provider("http://127.0.0.1:18888")


def test_the_adapter_accepts_loopback_under_the_exemption() -> None:
    provider = _provider("http://127.0.0.1:18888/", allow_loopback=True)

    assert provider.name == "hindsight"


def test_the_exemption_does_not_widen_anything_else() -> None:
    with pytest.raises(ValueError, match="approved private host"):
        _provider("https://memory.example.com", allow_loopback=True)
    with pytest.raises(ValueError, match="credentials or a path"):
        _provider("http://127.0.0.1:18888/v1", allow_loopback=True)


def test_configuration_and_the_adapter_agree_about_a_development_loopback_endpoint() -> None:
    """The regression that mattered: what startup accepts, the adapter must construct."""

    settings = _hindsight_settings("http://127.0.0.1:18888", memory_allow_loopback=True)
    assert settings.memory_hindsight_base_url == "http://127.0.0.1:18888"

    provider = _provider(
        settings.memory_hindsight_base_url,
        allow_loopback=settings.memory_allow_loopback,
    )
    assert provider.name == "hindsight"


def test_composition_builds_a_loopback_memory_provider_in_development_mode() -> None:
    from sidekick.api.app import create_container

    settings = Settings(
        _env_file=None,
        memory_enabled=True,
        memory_provider="hindsight",
        memory_hindsight_base_url="http://127.0.0.1:18888",
        memory_hindsight_api_token=TOKEN,  # type: ignore[arg-type]
        memory_id_derivation_key=DERIVATION_KEY,  # type: ignore[arg-type]
        memory_allow_loopback=True,
    )
    container = create_container(settings)

    assert isinstance(container.memory, HindsightMemoryProvider)


@pytest.mark.parametrize("environment", ["development", "test", "production"])
def test_configuration_and_the_adapter_both_refuse_loopback_without_the_flag(
    environment: str,
) -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="approved private host"):
        _hindsight_settings("http://127.0.0.1:18888", environment)
    with pytest.raises(ValueError, match="approved private host"):
        _provider("http://127.0.0.1:18888")


def test_the_loopback_flag_is_refused_in_production() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="not valid in production"):
        _hindsight_settings("http://127.0.0.1:18888", "production", memory_allow_loopback=True)


def test_composition_still_refuses_loopback_without_the_flag() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError, match="approved private host"):
        Settings(_env_file=None, memory_hindsight_base_url="http://127.0.0.1:18888")
