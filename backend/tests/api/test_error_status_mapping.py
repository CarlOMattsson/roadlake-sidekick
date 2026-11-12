"""Every error class answers with the status and fixed title it declares, never its own text."""

from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from sidekick.api.app import create_app
from sidekick.shared.errors import (
    AuthenticationRequiredError,
    ConflictError,
    NotFoundError,
    PermissionDeniedError,
    ValidationError,
)
from sidekick.shared.errors.core import RateLimitedError, SidekickError
from tests.support.settings import make_settings

CORRELATION = "a3f5c7b1-8d2e-4f6a-9b0c-1d2e3f4a5b6c"


@pytest.mark.parametrize(
    ("error_type", "status", "code", "title"),
    [
        (AuthenticationRequiredError, 401, "unauthorized", "Authentication required"),
        (PermissionDeniedError, 403, "forbidden", "Forbidden"),
        (NotFoundError, 404, "not_found", "Not found"),
        (ConflictError, 409, "conflict", "Conflict"),
        (ValidationError, 422, "validation_error", "Request validation failed"),
        (RateLimitedError, 400, "rate_limited", "Request failed"),
        (SidekickError, 400, "sidekick_error", "Request failed"),
    ],
)
def test_an_error_class_is_answered_with_its_declared_status_and_title(
    error_type: type[SidekickError], status: int, code: str, title: str
) -> None:
    app = create_app(make_settings())

    @app.get("/test/raises")
    def raises() -> None:
        raise error_type("secret detail: owner@example.com")

    with TestClient(app) as client:
        response = client.get("/test/raises", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == status
    assert response.headers["x-correlation-id"] == CORRELATION
    body = response.json()
    assert (body["code"], body["title"]) == (code, title)
    assert "proposal_id" not in body
    assert "secret detail" not in response.text


def test_an_error_that_names_its_proposal_sends_only_that_id() -> None:
    app = create_app(make_settings())
    proposal_id = uuid4()

    class StaleProposal(ConflictError):
        def __init__(self) -> None:
            super().__init__("secret detail: owner@example.com")
            self.proposal_id = proposal_id

    @app.get("/test/stale")
    def stale() -> None:
        raise StaleProposal()

    with TestClient(app) as client:
        response = client.get("/test/stale", headers={"x-correlation-id": CORRELATION})

    assert response.status_code == 409
    assert response.json()["proposal_id"] == str(proposal_id)
    assert "secret detail" not in response.text
