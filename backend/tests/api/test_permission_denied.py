"""A refused scope answers 403 `forbidden` over HTTP, whatever its text says."""

from uuid import uuid4

from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.shared.errors import AuthenticationRequiredError
from sidekick.shared.types import Actor
from tests.support.settings import make_settings

CORRELATION = "a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c"


def test_a_missing_scope_is_a_403_problem_without_the_scope_name() -> None:
    app = create_app(make_settings())

    @app.get("/test/needs-scope")
    def needs_scope() -> None:
        Actor(uuid4(), frozenset({"tasks:read"})).require("tasks:write")

    with TestClient(app) as client:
        response = client.get("/test/needs-scope", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 403
    assert response.headers["content-type"] == "application/problem+json"
    assert response.headers["x-correlation-id"] == CORRELATION
    body = response.json()
    assert (body["code"], body["title"]) == ("forbidden", "Forbidden")
    assert "tasks:write" not in response.text


def test_a_missing_identity_is_a_401_problem_without_the_error_text() -> None:
    app = create_app(make_settings())

    @app.get("/test/needs-identity")
    def needs_identity() -> None:
        raise AuthenticationRequiredError("secret detail: owner@example.com")

    with TestClient(app) as client:
        response = client.get("/test/needs-identity", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 401
    assert response.headers["x-correlation-id"] == CORRELATION
    body = response.json()
    assert (body["code"], body["title"]) == ("unauthorized", "Authentication required")
    assert "secret detail" not in response.text
