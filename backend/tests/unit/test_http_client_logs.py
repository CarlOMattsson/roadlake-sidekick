"""Every installed HTTP client library has its loggers silenced, in every kind of process.

httpx and httpcore log request URLs, and a push endpoint or topic is a capability. The same
libraries ship twice (`httpx2`, `httpcore2`), so a new client package or logger name must not slip
past the one list that silences them.
"""

import importlib
import importlib.metadata
import logging
import pkgutil
import re
from collections.abc import Callable, Iterator
from uuid import UUID

import httpx
import pytest

from sidekick.companion.push_sender import create_client
from sidekick.mcp.auth import GitHubIdentityVerifier
from sidekick.memory.adapters.hindsight import HindsightMemoryProvider
from sidekick.shared.observability import (
    HTTP_CLIENT_LOGGERS,
    NoopTelemetryAdapter,
    configure_worker_logging,
    harden_third_party_logging,
    silence_http_client_loggers,
)
from tests.support.third_party_logs import restored_logging  # noqa: F401  (fixture)

CLIENT_PACKAGE = re.compile(r"^(httpx|httpcore)\d*$")


def installed_client_packages() -> list[str]:
    names = {
        dist.metadata["Name"].lower().replace("-", "_")
        for dist in importlib.metadata.distributions()
    }
    return sorted(name for name in names if CLIENT_PACKAGE.match(name))


def logger_names_of(package: str) -> Iterator[str]:
    """Import the package and every submodule, then yield each logger created under its name."""

    module = importlib.import_module(package)
    for info in pkgutil.walk_packages(module.__path__, f"{package}."):
        try:
            importlib.import_module(info.name)
        except ImportError:  # an optional extra (socks, h2, trio) that is not installed
            continue
    for name in list(logging.root.manager.loggerDict):
        if name == package or name.startswith(f"{package}."):
            yield name


def is_covered(name: str) -> bool:
    return any(name == root or name.startswith(f"{root}.") for root in HTTP_CLIENT_LOGGERS)


def test_the_repo_installs_both_http_client_generations() -> None:
    assert {"httpx", "httpcore", "httpx2", "httpcore2"} <= set(installed_client_packages())


@pytest.mark.parametrize("package", installed_client_packages())
def test_every_logger_of_an_installed_client_package_is_covered(package: str) -> None:
    names = list(logger_names_of(package))

    assert names, f"{package} created no logger; the discovery is blind"
    assert [name for name in names if not is_covered(name)] == []


def test_silencing_holds_every_client_logger_and_its_children_at_warning() -> None:
    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    silence_http_client_loggers()

    for package in installed_client_packages():
        for name in logger_names_of(package):
            logger = logging.getLogger(name)
            assert not logger.isEnabledFor(logging.INFO), name
            assert not logger.isEnabledFor(logging.DEBUG), name


@pytest.mark.parametrize(
    "configure", [configure_worker_logging, harden_third_party_logging], ids=["worker", "api"]
)
def test_each_process_kind_silences_the_client_loggers_when_it_configures_logging(
    configure: Callable[[], object],
    restored_logging: None,  # noqa: F811
) -> None:
    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    configure()

    for name in HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).level == logging.WARNING


class ActiveUsers:
    def is_user_active(self, user_id: UUID) -> bool:
        return True


def build_push_client() -> object:
    with create_client() as client:
        return client


def build_hindsight_provider() -> object:
    with httpx.Client() as client:
        return HindsightMemoryProvider(
            base_url="http://127.0.0.1:18888",
            api_token="client-log-test-token",
            id_derivation_key="client-log-test-key",
            allow_loopback=True,
            client=client,
        )


def build_github_verifier() -> object:
    return GitHubIdentityVerifier(
        users=ActiveUsers(),
        identities={},
        scopes=frozenset(),
        telemetry=NoopTelemetryAdapter(),
        upstream_cache_seconds=60,
    )


@pytest.mark.parametrize(
    "build",
    [build_push_client, build_hindsight_provider, build_github_verifier],
    ids=["push-sender", "hindsight-adapter", "github-identity-verifier"],
)
def test_each_http_client_owner_silences_the_loggers_when_it_builds_its_client(
    build: Callable[[], object],
    restored_logging: None,  # noqa: F811
) -> None:
    for name in HTTP_CLIENT_LOGGERS:
        logging.getLogger(name).setLevel(logging.NOTSET)

    build()

    for name in HTTP_CLIENT_LOGGERS:
        assert logging.getLogger(name).level >= logging.WARNING, name
