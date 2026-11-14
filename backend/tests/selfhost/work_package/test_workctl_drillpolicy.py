"""The rules of tools/drill.sh: project names, ports, the image pair and what a push reports."""

from pathlib import Path

import pytest
from tools.workctl import drillpolicy

from tests.selfhost.work_package.support import REPO_ROOT

DIGEST = "sha256:" + "a" * 64
FROM = "registry.example/sidekick@" + DIGEST
TO = "registry.example/sidekick@sha256:" + "b" * 64


@pytest.mark.parametrize(
    ("value", "ports"),
    [
        ("9000", [9000]),
        (" 030000, 9000", [30000, 9000]),
        ("1,65535", [1, 65535]),
        ("9000,,9001, ", [9000, 9001]),
        (" , ", []),
    ],
)
def test_extra_reserved_ports_are_normalised_to_decimal(value: str, ports: list[int]) -> None:
    assert drillpolicy.extra_reserved_ports(value) == ports


@pytest.mark.parametrize(
    "value", ["abc", "70000", "0", "000", "9000\n9001", "55436,x", "9000;1", "-1", "9 000x"]
)
def test_a_malformed_reserved_ports_value_is_refused(value: str) -> None:
    with pytest.raises(
        drillpolicy.Refused, match="SIDEKICK_RESERVED_PORTS must be comma-separated"
    ):
        drillpolicy.extra_reserved_ports(value)


def test_the_image_pair_must_be_given_pinned_and_different() -> None:
    drillpolicy.check_image_pair(FROM, TO)
    with pytest.raises(drillpolicy.Refused, match="are required, or --local-images"):
        drillpolicy.check_image_pair("", TO)
    with pytest.raises(drillpolicy.Refused, match="are required"):
        drillpolicy.check_image_pair(FROM, "")
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair("registry.example/sidekick:1.0", TO)
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair(FROM, "registry.example/sidekick@sha256:abc")
    with pytest.raises(drillpolicy.Refused, match="must differ"):
        drillpolicy.check_image_pair(FROM, FROM)


@pytest.mark.parametrize(
    "image", ["Registry/x@" + DIGEST, "x@" + DIGEST + "\n", "@" + DIGEST, "x y@" + DIGEST]
)
def test_a_digest_pin_has_no_uppercase_blank_or_trailing_newline(image: str) -> None:
    with pytest.raises(drillpolicy.Refused, match="pinned by digest"):
        drillpolicy.check_image_pair(image, TO)


def test_a_picked_port_is_never_reserved_used_or_listening(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    candidates = iter([20000, 20001, 20002, 20003])
    asked: list[tuple[int, int]] = []

    def randint(low: int, high: int) -> int:
        asked.append((low, high))
        return next(candidates)

    monkeypatch.setattr(drillpolicy.random, "randint", randint)
    port = drillpolicy.pick_port([20000], [20001], lambda candidate: candidate == 20002)
    assert port == 20003
    assert asked == [(20000, 39999)] * 4


def test_a_listening_port_is_skipped_and_the_search_gives_up_after_50_tries() -> None:
    tried: list[int] = []

    def busy(port: int) -> bool:
        tried.append(port)
        return True

    assert drillpolicy.pick_port([], [], busy) is None
    assert len(tried) == drillpolicy.PICK_ATTEMPTS


def test_a_port_that_something_listens_on_is_detected() -> None:
    import socket

    with socket.socket() as server:
        server.bind(("127.0.0.1", 0))
        server.listen(1)
        busy = server.getsockname()[1]
        assert drillpolicy.listening(busy)
    assert not drillpolicy.listening(busy)


def test_the_last_digest_of_a_push_is_taken() -> None:
    output = (
        "The push refers to repository [127.0.0.1:1/sidekick]\n"
        "from: digest: sha256:" + "1" * 64 + " size: 1\n"
        "to: digest: " + DIGEST + " size: 2\n"
        "digest: sha256:short\n"
    )
    assert drillpolicy.pushed_digest(output) == DIGEST
    assert drillpolicy.pushed_digest("no digest here\n") is None
    assert drillpolicy.pushed_digest("") is None


def test_the_release_versions_are_the_source_version_and_the_next_patch(tmp_path: Path) -> None:
    pyproject = tmp_path / "pyproject.toml"
    pyproject.write_text('[project]\nversion = "0.9.9"\n', encoding="utf-8")
    assert drillpolicy.release_versions(pyproject) == ("0.9.9", "0.9.10")
    real = drillpolicy.release_versions(REPO_ROOT / "backend" / "pyproject.toml")
    assert all(part.isdigit() for version in real for part in version.split("."))


@pytest.mark.parametrize("name", ["sk-drill-a", "sk-drill-0f3a-sh", "sk-drill-x-y-1"])
def test_a_drill_project_name_is_accepted(name: str) -> None:
    assert drillpolicy.require_project(name) == name


@pytest.mark.parametrize(
    "name",
    [
        "",
        "evil",
        "my-drill-x",
        "SK-DRILL-x",
        "sk-drill-",
        "sk-drill--x",
        "sk-drill-a b",
        "sk-drill-../x",
        "sk-drill-a\n",
    ],
)
def test_any_other_project_name_is_refused(name: str) -> None:
    with pytest.raises(drillpolicy.Refused, match="must start with sk-drill-"):
        drillpolicy.require_project(name)
    assert not drillpolicy.valid_project(name)


def test_the_default_reserved_ports_are_the_long_running_instances_and_the_test_pool() -> None:
    assert set(drillpolicy.RESERVED_PORTS) == {55432, 55433, 55434, 55436, 8100, 8101}
