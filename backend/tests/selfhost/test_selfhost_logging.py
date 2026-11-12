"""Self-hosted logging: rotated container logs and an allowlisted Caddy access log."""

import json
import re
import shutil
import subprocess
import uuid
from pathlib import Path

import pytest
import yaml

from tests.support.polling import poll_until

SELFHOST = Path(__file__).resolve().parents[3] / "deploy" / "selfhost"
# The only top-level fields besides Caddy's own fixed ones (time, level, logger, message, status,
# duration, size) that an access log line may carry. `route` is a fixed label, never the path.
APPENDED_FIELDS = {
    "method": "{http.request.method}",
    "host": "{http.request.host}",
    "route": "{route_class}",
    "request_id": "{http.request.uuid}",
}
ROUTE_CLASSES = {"oauth", "mcp", "well-known", "companion", "push", "unmatched"}
ACCESS_LOG_KEYS = {
    "level",
    "ts",
    "logger",
    "msg",
    "duration",
    "size",
    "status",
    "request_id",
    "route",
    "host",
    "method",
}


@pytest.fixture(name="services")
def _services() -> dict[str, dict]:
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    return compose["services"]


@pytest.fixture(name="caddy")
def _caddy() -> str:
    return (SELFHOST / "Caddyfile.example").read_text(encoding="utf-8")


def _site_log_block(caddy: str) -> str:
    """The body of the site block's `log { ... }` (the global logger sits before the site)."""
    site = caddy.split("{$SIDEKICK_DOMAIN} {", 1)[1]
    return site.split("\tlog {", 1)[1].split("\n\t}\n", 1)[0]


def test_every_service_rotates_its_container_log(services: dict[str, dict]) -> None:
    assert services
    for name, service in services.items():
        logging = service.get("logging")
        assert logging is not None, f"{name} has no logging limits"
        assert logging["driver"] == "json-file", name
        assert re.fullmatch(r"\d+[kmg]", logging["options"]["max-size"]), name
        assert int(logging["options"]["max-file"]) >= 2, name


def test_all_services_share_one_rotation_setting(services: dict[str, dict]) -> None:
    assert len({repr(service["logging"]) for service in services.values()}) == 1


def test_the_access_log_appends_exactly_the_reviewed_fields(caddy: str) -> None:
    appended = dict(re.findall(r"^\tlog_append (\w+) (\S+)$", caddy, re.M))
    assert appended == APPENDED_FIELDS


def test_the_access_log_deletes_whole_objects_instead_of_single_headers(caddy: str) -> None:
    # `request` holds the client address, every header and the query string: it goes as a whole,
    # so a field Caddy adds to it later cannot reach a log line.
    block = _site_log_block(caddy)
    for field in ("request", "resp_headers", "user_id", "bytes_read", "uuid"):
        assert re.search(rf"^\t+{field} delete$", block, re.M), field
    assert "request>" not in block
    assert "Authorization" not in block


def test_the_access_log_carries_a_route_class_never_the_path(caddy: str) -> None:
    # Only fixed labels are logged: no placeholder holds the path, the URI or the query string.
    for line in re.findall(r"^\tlog_append .*$", caddy, re.M):
        assert "uri" not in line and "path" not in line, line
    assert "uri.query" not in caddy and "{http.request.uri}" not in caddy
    block = caddy.split("\tmap {http.request.uri.path} {route_class} {", 1)[1].split("\n\t}\n", 1)[
        0
    ]
    rules = [line.strip() for line in block.strip().splitlines()]
    assert {rule.split()[-1] for rule in rules} == ROUTE_CLASSES
    assert rules[-1] == "default unmatched"
    # No path rewriting is left in the log block: the path is not logged at all.
    assert "path" not in _site_log_block(caddy)


def test_the_default_logger_drops_the_request_of_proxy_errors_too(caddy: str) -> None:
    # A failed proxy attempt is written by Caddy's default logger with the URI (path and query).
    head = caddy.split("{$SIDEKICK_DOMAIN} {", 1)[0]
    block = re.search(r"^\{\n\tlog \{\n(.*?)\n\t\}\n\}\n", head, re.M | re.S)
    assert block is not None
    assert "wrap json" in block.group(1)
    assert re.search(r"^\t+request delete$", block.group(1), re.M)


def _caddy_image() -> str | None:
    """The pinned Caddy image if docker is present and the image is already local (never pulled)."""
    if shutil.which("docker") is None:
        return None
    compose = yaml.safe_load((SELFHOST / "compose.yaml").read_text(encoding="utf-8"))
    image = compose["services"]["caddy"]["image"]
    inspect = subprocess.run(
        ["docker", "image", "inspect", image], capture_output=True, check=False
    )
    return image if inspect.returncode == 0 else None


@pytest.fixture(name="caddy_dir")
def _caddy_dir(tmp_path: Path) -> Path:
    example = (SELFHOST / "Caddyfile.example").read_text(encoding="utf-8")
    (tmp_path / "Caddyfile").write_text(example, encoding="utf-8")
    return tmp_path


def test_caddy_validates_the_example(caddy_dir: Path) -> None:
    image = _caddy_image()
    if image is None:
        pytest.skip("docker or the pinned caddy image is not available locally")
    command = [
        "docker",
        "run",
        "--rm",
        "--network",
        "none",
        "-e",
        "SIDEKICK_DOMAIN=example.test",
        "-v",
        f"{caddy_dir}:/etc/caddy:ro",
        image,
        "caddy",
        "validate",
        "--config",
        "/etc/caddy/Caddyfile",
    ]
    result = subprocess.run(command, capture_output=True, text=True, timeout=120, check=False)
    assert result.returncode == 0, result.stderr[-2000:]


def test_a_running_caddy_logs_no_raw_path_query_or_header(caddy_dir: Path) -> None:
    image = _caddy_image()
    if image is None:
        pytest.skip("docker or the pinned caddy image is not available locally")
    name = f"sidekick-caddylog-test-{uuid.uuid4().hex[:8]}"
    probes = {
        "/mcp/synthetic-private-marker?code=synthetic-query": "mcp",
        "/mcp/token": "oauth",
        "/.well-known/oauth-protected-resource/mcp": "well-known",
        "/companion/v1/tasks/0f0f0f0f-0f0f-0f0f-0f0f-0f0f0f0f0f0f/complete": "companion",
        "/upsyntheticTopic1/json": "push",
        "/synthetic-probe-path": "unmatched",
    }
    started = subprocess.run(
        [
            "docker",
            "run",
            "-d",
            "--name",
            name,
            "--network",
            "none",
            "-e",
            "SIDEKICK_DOMAIN=http://localhost",
            "-v",
            f"{caddy_dir}:/etc/caddy:ro",
            image,
        ],
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )
    assert started.returncode == 0, started.stderr
    try:

        def listening() -> bool:
            ready = subprocess.run(
                ["docker", "exec", name, "wget", "-q", "-O", "/dev/null", "http://localhost/ready"],
                capture_output=True,
                check=False,
            )
            # busybox wget: 1 = generic failure (connection refused); anything else means it
            # answered, so a 404 for /ready is fine.
            return ready.returncode != 1

        poll_until(listening, timeout=10, interval=0.5)
        for path in probes:
            subprocess.run(
                [
                    "docker",
                    "exec",
                    name,
                    "wget",
                    "-q",
                    "-O",
                    "/dev/null",
                    "--header",
                    "Authorization: Bearer synthetic-token",
                    f"http://localhost{path}",
                ],
                capture_output=True,
                check=False,
            )
        logs = subprocess.run(["docker", "logs", name], capture_output=True, text=True, check=False)
    finally:
        subprocess.run(["docker", "rm", "-f", name], capture_output=True, check=False)
    text = logs.stdout + logs.stderr
    for marker in (
        "synthetic-private-marker",
        "synthetic-query",
        "synthetic-token",
        "synthetic-probe-path",
        "syntheticTopic1",
        "0f0f0f0f",
        "/mcp/token",
        '"uri"',
    ):
        assert marker not in text, marker
    access = [json.loads(line) for line in text.splitlines() if '"logger":"http.log.access' in line]
    probe_lines = access[-len(probes) :]
    assert [entry["route"] for entry in probe_lines] == list(probes.values())
    for entry in access:
        assert set(entry) <= ACCESS_LOG_KEYS, set(entry) - ACCESS_LOG_KEYS
