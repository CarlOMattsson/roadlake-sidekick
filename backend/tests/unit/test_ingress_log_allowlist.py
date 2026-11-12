"""The HTTP ingress log line is built from a closed allow-list, not by filtering a larger record."""

import dataclasses
import io
import json
import logging
from collections.abc import Iterator

import pytest
from starlette.routing import Route
from starlette.types import Message, Receive, Scope, Send

from sidekick.shared.observability import (
    SAFE_LOG_FIELDS,
    AllowlistJsonFormatter,
    CorrelationMiddleware,
    IngressLogRecord,
    NoopTelemetryAdapter,
    route_template,
)

SECRET_ID = "anna.svensson@example.com"
TOKEN = "rsc_0123456789abcdef0123456789abcdef"
EXPECTED_FIELDS = {"correlation_id", "http_method", "http_route", "http_status", "duration_ms"}
_STANDARD_RECORD_ATTRIBUTES = set(vars(logging.LogRecord("n", 0, "p", 0, "m", None, None)))


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="logs")
def _logs() -> Iterator[_Collector]:
    collector = _Collector()
    logger = logging.getLogger("sidekick.http")
    previous = logger.level
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)
        logger.setLevel(previous)


async def _app(scope: Scope, receive: Receive, send: Send) -> None:
    await send({"type": "http.response.start", "status": 200, "headers": []})
    await send({"type": "http.response.body", "body": b""})


async def _call(scope_extra: dict[str, object]) -> None:
    async def receive() -> Message:
        return {"type": "http.request", "body": SECRET_ID.encode()}

    async def send(_message: Message) -> None:
        return None

    scope: Scope = {
        "type": "http",
        "method": "POST",
        "path": f"/companion/v1/tasks/{SECRET_ID}",
        "raw_path": f"/companion/v1/tasks/{SECRET_ID}".encode(),
        "query_string": f"code={TOKEN}&email={SECRET_ID}".encode(),
        "client": ("203.0.113.9", 51234),
        "server": ("sidekick.internal", 8000),
        "headers": [
            (b"authorization", f"Bearer {TOKEN}".encode()),
            (b"cookie", f"session={TOKEN}".encode()),
            (b"user-agent", SECRET_ID.encode()),
            (b"x-forwarded-for", b"198.51.100.4"),
        ],
        **scope_extra,
    }
    await CorrelationMiddleware(_app, NoopTelemetryAdapter())(scope, receive, send)


def test_the_record_type_is_exactly_the_reviewed_field_set() -> None:
    assert {field.name for field in dataclasses.fields(IngressLogRecord)} == EXPECTED_FIELDS
    assert EXPECTED_FIELDS <= SAFE_LOG_FIELDS
    record = IngressLogRecord("c", "GET", "/x", 200, 1.5)
    assert set(record.fields()) == EXPECTED_FIELDS
    with pytest.raises(TypeError):
        IngressLogRecord("c", "GET", "/x", 200, 1.5, extra=SECRET_ID)  # type: ignore[call-arg]  # pyright: ignore[reportCallIssue]


@pytest.mark.asyncio
async def test_secrets_in_path_query_headers_client_and_body_never_reach_the_record(
    logs: _Collector,
) -> None:
    await _call({"route": Route("/companion/v1/tasks/{task_id}", _app)})

    (record,) = logs.records
    attributes = vars(record)
    extras = {
        key: value
        for key, value in attributes.items()
        if key not in _STANDARD_RECORD_ATTRIBUTES | {"message", "asctime", "taskName"}
    }
    assert set(extras) == EXPECTED_FIELDS
    assert extras["http_route"] == "/companion/v1/tasks/{task_id}"
    assert extras["http_method"] == "POST"
    assert extras["http_status"] == 200
    rendered = repr(attributes)
    for forbidden in (SECRET_ID, TOKEN, "203.0.113.9", "198.51.100.4", "sidekick.internal"):
        assert forbidden not in rendered


@pytest.mark.asyncio
async def test_the_json_line_holds_the_template_and_no_dropped_field(logs: _Collector) -> None:
    await _call({"route": Route("/companion/v1/tasks/{task_id}", _app)})

    stream = io.StringIO()
    handler = logging.StreamHandler(stream)
    handler.setFormatter(AllowlistJsonFormatter("%(levelname)s %(name)s %(message)s"))
    handler.handle(logs.records[0])
    line = json.loads(stream.getvalue())
    assert line["http_route"] == "/companion/v1/tasks/{task_id}"
    assert "dropped_field_count" not in line
    assert SECRET_ID not in stream.getvalue()
    assert TOKEN not in stream.getvalue()


@pytest.mark.parametrize("route", [None, object(), 42])
def test_a_request_that_matched_no_route_is_logged_as_unmatched(route: object) -> None:
    scope: Scope = {"type": "http", "path": f"/{SECRET_ID}"}
    if route is not None:
        scope["route"] = route
    assert route_template(scope) == "unmatched"


def test_an_over_long_template_is_not_logged() -> None:
    scope: Scope = {"type": "http", "route": Route("/" + "a" * 200, _app)}
    assert route_template(scope) == "unmatched"
