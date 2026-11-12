"""Health, compression and the absence of a web sign-in on the HTTP API."""

import pytest
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from tests.db import database_factory
from tests.support.settings import (
    make_settings,
)


@pytest.mark.parametrize(
    ("method", "path"),
    [
        ("GET", "/api/v1/auth/csrf"),
        ("POST", "/api/v1/auth/login"),
        ("POST", "/api/v1/auth/logout"),
        ("GET", "/api/v1/session"),
        ("GET", "/api/v1/shopping/lists"),
        ("POST", "/api/v1/shopping/lists"),
    ],
)
def test_the_removed_web_sign_in_and_session_routes_do_not_exist(method: str, path: str) -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        response = client.request(method, path, json={})
    assert response.status_code == 404


def test_the_http_api_offers_no_cookie_or_session_authentication() -> None:
    app = create_app(make_settings())
    with TestClient(app) as client:
        document = client.get("/api/openapi.json").json()
    assert not [path for path in document["paths"] if path.startswith("/api/v1")]
    assert "securitySchemes" not in document.get("components", {})


@pytest.mark.integration
def test_health() -> None:
    app = create_app(make_settings(), database_factory())
    with TestClient(app) as client:
        assert client.get("/health/live").json() == {"status": "ok"}
        assert client.get("/health/ready").json() == {"status": "ok"}


def test_large_json_is_gzipped_on_request_and_small_json_is_not() -> None:
    app = create_app(make_settings())

    @app.get("/test/large")
    def large_json() -> dict[str, list[str]]:
        return {"items": [f"item-{index:04d}" for index in range(400)]}

    with TestClient(app) as client:
        large = client.get("/test/large", headers={"Accept-Encoding": "gzip"})
        large_identity = client.get("/test/large", headers={"Accept-Encoding": "identity"})
        small = client.get("/health/live", headers={"Accept-Encoding": "gzip"})
    assert large.status_code == 200
    assert large.headers["content-encoding"] == "gzip"
    assert large.num_bytes_downloaded < len(large_identity.content)
    assert "content-encoding" not in large_identity.headers
    assert large.json() == large_identity.json()
    assert small.status_code == 200
    assert "content-encoding" not in small.headers
    assert small.json() == {"status": "ok"}
