"""An exception no handler claims becomes a safe, structured 500 with the correlation id."""

import logging
from collections.abc import Iterator

import pytest
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.companion.push import PushSubscriptionService
from sidekick.shared.errors import InvalidInputError
from sidekick.shared.errors.core import InternalFaultError
from tests.support.companion import bearer, companion_app, owner, paired_token
from tests.support.settings import make_settings

SECRET = "secret: anna.svensson@example.com SELECT * FROM users"
CORRELATION = "a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c"


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)

    def rendered(self) -> str:
        return "\n".join(repr(vars(record)) for record in self.records)


@pytest.fixture(name="logs")
def _logs() -> Iterator[_Collector]:
    collector = _Collector()
    logger = logging.getLogger("sidekick.api.errors")
    logger.addHandler(collector)
    logger.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        logger.removeHandler(collector)


def test_an_unexpected_exception_returns_the_safe_envelope_with_the_correlation_id(
    logs: _Collector,
) -> None:
    app = create_app(make_settings())

    @app.get("/test/boom")
    def boom() -> None:
        raise RuntimeError(SECRET)

    with TestClient(app) as client:
        response = client.get("/test/boom", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 500
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-correlation-id"] == CORRELATION
    assert response.json() == {
        "type": "urn:sidekick:error:internal_error",
        "title": "Internal server error",
        "status": 500,
        "code": "internal_error",
        "correlation_id": CORRELATION,
    }
    assert "secret" not in response.text and "SELECT" not in response.text
    assert "Traceback" not in response.text
    (record,) = logs.records
    assert vars(record)["error_type"] == "RuntimeError"
    assert vars(record)["correlation_id"] == CORRELATION
    assert "secret" not in logs.rendered() and "anna.svensson" not in logs.rendered()


def test_a_failing_async_route_and_a_missing_correlation_id_are_covered_too() -> None:
    app = create_app(make_settings())

    @app.post("/test/async-boom")
    async def boom() -> None:
        raise KeyError(SECRET)

    with TestClient(app) as client:
        response = client.post("/test/async-boom", json={})

    body = response.json()
    assert response.status_code == 500
    assert body["code"] == "internal_error"
    assert body["correlation_id"] == response.headers["x-correlation-id"]
    assert body["correlation_id"] != "unknown"
    assert "secret" not in response.text


def test_known_errors_keep_their_own_status() -> None:
    app = create_app(make_settings())

    @app.get("/test/value")
    def value() -> None:
        raise InvalidInputError(SECRET)

    with TestClient(app) as client:
        response = client.get("/test/value")
    assert response.status_code == 400
    assert response.json()["code"] == "bad_request"
    assert "secret" not in response.text


def test_a_plain_value_error_is_an_internal_error_not_a_client_error(logs: _Collector) -> None:
    app = create_app(make_settings())

    @app.get("/test/value")
    def value() -> None:
        raise ValueError(SECRET)

    with TestClient(app) as client:
        response = client.get("/test/value", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["correlation_id"] == CORRELATION
    assert "secret" not in response.text and "secret" not in logs.rendered()
    (record,) = logs.records
    assert vars(record)["error_type"] == "ValueError"


@pytest.mark.integration
def test_an_unexpected_error_in_a_companion_route_is_the_same_safe_envelope(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    app = companion_app()
    user_id = owner(app)

    def broken(*_args: object, **_kwargs: object) -> str:
        raise KeyError(SECRET)

    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        monkeypatch.setattr(PushSubscriptionService, "subscribe", broken)
        response = client.put(
            "/companion/v1/push/subscription",
            json={"endpoint": "https://push.example.org/up"},
            headers={**bearer(token), "x-correlation-id": CORRELATION},
        )

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["correlation_id"] == CORRELATION
    assert response.headers["x-correlation-id"] == CORRELATION
    assert "secret" not in response.text


def test_an_internal_fault_error_is_a_generic_500_without_its_text(logs: _Collector) -> None:
    app = create_app(make_settings())

    @app.get("/test/fault")
    def fault() -> None:
        raise InternalFaultError(SECRET)

    with TestClient(app) as client:
        response = client.get("/test/fault", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 500
    assert response.json()["code"] == "internal_error"
    assert response.json()["correlation_id"] == CORRELATION
    assert "anna.svensson" not in response.text
    assert "anna.svensson" not in logs.rendered()
