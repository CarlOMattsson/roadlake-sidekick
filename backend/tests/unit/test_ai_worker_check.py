"""The AI worker's loop with the check beside the runner: what it builds, what it drains, and what
makes its healthcheck report. No database and no model: the services are stand-ins."""

import os
import threading
from collections.abc import Callable
from pathlib import Path
from typing import Any, ClassVar

import pytest

from sidekick.shared.config import Settings
from sidekick.shared.errors import RefusedError
from sidekick.shared.observability import NoopTelemetryAdapter
from sidekick.work import ai_worker
from sidekick.work.ai_worker import build_checker, run_worker

KEY = "sk-or-" + "k" * 30


class Beats:
    """Stands in for the heartbeat file."""

    instances: ClassVar[list["Beats"]] = []

    def __init__(self, name: str) -> None:
        self.beats = 0
        self.successes = 0
        Beats.instances.append(self)

    def beat(self, sleep_seconds: float) -> None:
        self.beats += 1

    def succeeded(self) -> None:
        self.successes += 1


class FakeService:
    """A runner or a check: `waiting` runs to take, then none."""

    def __init__(self, waiting: int = 0, *, rejected: bool = False, fail: bool = False) -> None:
        self.waiting = waiting
        self.credentials_rejected = rejected
        self.fail = fail
        self.taken: list[str] = []
        self.progress: Callable[[], None] = lambda: None

    def run_next(self, worker_id: str) -> bool:
        if self.fail:
            raise RuntimeError("provider down")
        self.taken.append(worker_id)
        if self.waiting == 0:
            return False
        self.waiting -= 1
        return True

    def recover_stalled(self) -> int:
        return 0


@pytest.fixture(autouse=True)
def isolated(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    for name in [name for name in os.environ if name.startswith("SIDEKICK_AI_")]:
        monkeypatch.delenv(name)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(ai_worker, "WorkerHeartbeat", Beats)
    monkeypatch.setattr(ai_worker, "configure_observability", lambda _env: NoopTelemetryAdapter())
    Beats.instances.clear()


def settings(**fields: Any) -> Settings:
    return Settings(_env_file=None, ai_poll_seconds=1, **fields)


CHECK_ON: dict[str, Any] = {
    "ai_check_provider": "openai_compat",
    "ai_check_mode": "decisions",
    "ai_check_model": "typesafe/jev-1.14",
    "ai_check_base_url": "https://openrouter.ai",
}


def _refuse_runner(*_args: object) -> Any:
    raise AssertionError("the runner is off, so it must not be built")


def _builds(service: object) -> Any:
    """A `build_check` that hands out a stand-in service."""

    return lambda _settings, _stopping: service


def _releases(service: object) -> Any:
    """A `build_release` that hands out a stand-in service."""

    return lambda _settings: service


def test_with_the_runner_and_the_check_off_the_worker_still_releases_runs_nobody_checks() -> None:
    releases = FakeService(waiting=1)

    run_worker(
        settings(),
        once=True,
        build=_refuse_runner,
        build_check=_refuse_runner,
        build_release=_releases(releases),
    )

    assert len(releases.taken) == 1
    assert Beats.instances[0].successes == 1


def test_an_idle_worker_whose_release_fails_does_not_report_success() -> None:
    run_worker(
        settings(),
        once=True,
        build=_refuse_runner,
        build_check=_refuse_runner,
        build_release=_releases(FakeService(fail=True)),
    )

    assert Beats.instances[0].successes == 0


def test_the_check_alone_keeps_the_worker_busy_without_an_anthropic_key() -> None:
    checks = FakeService(waiting=2)

    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(checks),
        build_release=_releases(FakeService()),
    )

    assert len(checks.taken) == 1  # `once` takes one run
    assert Beats.instances[0].successes == 1


def test_the_worker_gives_the_check_a_way_to_prove_it_is_not_stuck() -> None:
    checks = FakeService()

    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(checks),
        build_release=_releases(FakeService()),
    )
    before = Beats.instances[0].beats
    checks.progress()

    assert Beats.instances[0].beats == before + 1


def test_runs_are_drained_until_none_waits() -> None:
    checks = FakeService(waiting=3)
    stop = threading.Event()
    seen: list[int] = []

    original = checks.run_next

    def counting(worker_id: str) -> bool:
        taken = original(worker_id)
        seen.append(len(checks.taken))
        if not taken:
            stop.set()
        return taken

    checks.run_next = counting  # type: ignore[method-assign]
    run_worker(
        settings(**CHECK_ON),
        stop=stop,
        build=_refuse_runner,
        build_check=_builds(checks),
        build_release=_releases(FakeService()),
    )

    assert seen == [1, 2, 3, 4]


def test_a_check_that_keeps_failing_does_not_report_success() -> None:
    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(FakeService(fail=True)),
        build_release=_releases(FakeService()),
    )

    assert Beats.instances[0].successes == 0


def test_a_refused_key_stops_the_success_beat() -> None:
    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(FakeService(rejected=True)),
        build_release=_releases(FakeService()),
    )

    assert Beats.instances[0].successes == 0


def test_the_check_is_not_built_while_it_is_off() -> None:
    assert build_checker(settings(), lambda: False) is None


def test_the_check_refuses_to_start_without_its_key() -> None:
    with pytest.raises(RefusedError, match="no key"):
        build_checker(settings(**CHECK_ON), lambda: False)


def test_the_check_is_built_with_its_key_without_opening_a_connection(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(ai_worker, "create_session_factory", lambda *_a, **_k: object())

    service = build_checker(settings(**CHECK_ON, ai_check_api_key=KEY), lambda: False)

    assert service is not None
    assert service.checker.model == "typesafe/jev-1.14"
    assert service.credentials_rejected is False
    # What the check cleared is applied for an automation whose owner opted in, by the same use
    # case the API applies an approval with.
    assert service.auto_applier is not None


def test_after_the_check_the_worker_ends_the_wait_of_runs_nobody_checks() -> None:
    order: list[str] = []
    checks = FakeService(waiting=1)
    releases = FakeService(waiting=1)
    checks_next, releases_next = checks.run_next, releases.run_next
    checks.run_next = lambda worker_id: order.append("check") or checks_next(worker_id)  # type: ignore[method-assign]
    releases.run_next = lambda worker_id: order.append("release") or releases_next(worker_id)  # type: ignore[method-assign]

    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(checks),
        build_release=_releases(releases),
    )

    assert order == ["check", "release"]
    assert Beats.instances[0].successes == 1


def test_a_release_that_fails_does_not_report_success() -> None:
    run_worker(
        settings(**CHECK_ON),
        once=True,
        build=_refuse_runner,
        build_check=_builds(FakeService()),
        build_release=_releases(FakeService(fail=True)),
    )

    assert Beats.instances[0].successes == 0
