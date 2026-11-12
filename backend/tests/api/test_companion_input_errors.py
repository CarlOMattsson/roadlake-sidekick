"""A malformed client value on a companion route is a client error, never an internal one.

Only `InvalidInputError` and the pydantic validation error are answered as client errors, so a
stdlib `ValueError` escaping a parser of client input would surface as a 500. Every route that
passes a client-supplied cursor or identifier through to a use case is probed here.
"""

from __future__ import annotations

import base64
from typing import Any

import pytest
from fastapi.testclient import TestClient

from tests.support.companion import bearer, companion_app, owner, paired_token
from tests.support.companion_work import seed_work

# Strings that are not a cursor this server issued: not base64, base64 of non-JSON, base64 of JSON
# that is not an object, the right length with a wrong signature, and non-ASCII text.
MALFORMED_CURSORS = [
    "!!!not-a-cursor",
    base64.urlsafe_b64encode(b"\xff\xfe not json").decode().rstrip("="),
    base64.urlsafe_b64encode(b'["a"]').decode().rstrip("="),
    base64.urlsafe_b64encode(b"x" * 80).decode().rstrip("="),
    "kursivå",
]


def cursor_paths(project_id: Any, task_id: Any) -> list[str]:
    return [
        "/companion/v1/work/agenda",
        "/companion/v1/work/today",
        f"/companion/v1/projects/{project_id}/tasks",
        f"/companion/v1/tasks/{task_id}/contacts",
        f"/companion/v1/tasks/{task_id}/external-references",
        "/companion/v1/journal/days/2026-11-11",
        "/companion/v1/journal/entries",
    ]


@pytest.mark.integration
@pytest.mark.parametrize("cursor", MALFORMED_CURSORS)
def test_a_malformed_cursor_is_a_client_error_on_every_paged_route(cursor: str) -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    with TestClient(app, raise_server_exceptions=False) as client:
        token = paired_token(client, app, user_id)
        for path in cursor_paths(work.project.id, work.task.id):
            response = client.get(path, params={"cursor": cursor}, headers=bearer(token))
            assert response.status_code in (400, 422), (path, response.status_code)
            assert response.json()["code"] in ("bad_request", "validation_error"), path


@pytest.mark.integration
@pytest.mark.parametrize(
    "path",
    [
        "/companion/v1/tasks/not-a-uuid",
        "/companion/v1/projects/not-a-uuid/tasks",
        "/companion/v1/journal/days/2026-02-30",
        "/companion/v1/journal/days/yesterday",
        "/companion/v1/journal/entries/not-a-uuid",
        "/companion/v1/journal/sources/not-a-uuid",
        "/companion/v1/journal/entries?from_date=2026-13-01",
        "/companion/v1/journal/entries?to_date=not-a-date",
    ],
)
def test_a_malformed_identifier_or_date_is_a_validation_error(path: str) -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        token = paired_token(client, app, user_id)
        response = client.get(path, headers=bearer(token))
    assert response.status_code == 422
    assert response.json()["code"] == "validation_error"


NUL_TEXT = "abc\x00def"
OTHER_ID = "00000000-0000-4000-8000-000000000001"
ENTRY_FIELDS = {"journal_date": "2026-11-11", "title": "T", "source_text": "S"}


def nul_write_calls() -> list[tuple[str, str, dict[str, Any]]]:
    """Every companion route that takes a JSON body, each with a NUL in one text field."""
    item = {"name": "Mjölk", "client_ref": "ref1"}
    items_path = f"/companion/v1/shopping/lists/{OTHER_ID}/items"
    item_update_path = f"/companion/v1/shopping/items/{OTHER_ID}/update"
    entry_update_path = f"/companion/v1/journal/entries/{OTHER_ID}/update"
    point = {"kind": "decision", "text": NUL_TEXT}
    return [
        ("POST", "/companion/v1/pair", {"pairing_secret": "x" * 20 + "\x00"}),
        ("PUT", "/companion/v1/push/subscription", {"endpoint": "https://push.example/a\x00b"}),
        ("PUT", "/companion/v1/license", {"key": NUL_TEXT}),
        ("POST", "/companion/v1/shopping/lists", {"name": NUL_TEXT}),
        (
            "POST",
            f"/companion/v1/shopping/lists/{OTHER_ID}/update",
            {"name": NUL_TEXT, "archived": False, "version": 1},
        ),
        *(
            ("POST", items_path, {"items": [{**item, field: NUL_TEXT}]})
            for field in ("name", "note", "unit", "store", "product_url", "occasion")
        ),
        *(
            ("POST", item_update_path, {"item": {field: NUL_TEXT}, "version": 1})
            for field in ("name", "note", "store")
        ),
        *(
            ("POST", "/companion/v1/journal/entries", {**ENTRY_FIELDS, **bad})
            for bad in (
                {"title": NUL_TEXT},
                {"source_text": NUL_TEXT},
                {"summary": NUL_TEXT},
                {"language": NUL_TEXT},
                {"key_points": [point]},
            )
        ),
        *(
            ("POST", entry_update_path, {"version": 1, **bad})
            for bad in (
                {"title": NUL_TEXT},
                {"summary": NUL_TEXT},
                {"append_text": NUL_TEXT},
                {"key_points": [point]},
                {"append_key_points": [point]},
            )
        ),
    ]


@pytest.mark.integration
def test_a_nul_character_in_a_request_body_is_a_validation_error_on_every_write_route() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app, raise_server_exceptions=False) as client:
        token = paired_token(client, app, user_id)
        for method, path, body in nul_write_calls():
            headers = {**bearer(token), "Idempotency-Key": "nul-key-000001"}
            response = client.request(method, path, json=body, headers=headers)
            assert response.status_code == 422, (path, body, response.status_code)
            assert response.json()["code"] == "validation_error", (path, body)
            assert "u0000" not in response.text and "\x00" not in response.text, path


@pytest.mark.integration
def test_a_nul_character_in_a_query_parameter_is_a_validation_error() -> None:
    app = companion_app()
    user_id = owner(app)
    work = seed_work(app, user_id)
    queries = [
        *((path, {"cursor": NUL_TEXT}) for path in cursor_paths(work.project.id, work.task.id)),
        ("/companion/v1/work/agenda", {"q": NUL_TEXT}),
        ("/companion/v1/work/agenda", {"tags": NUL_TEXT}),
        (f"/companion/v1/shopping/lists/{OTHER_ID}", {"store": NUL_TEXT}),
    ]
    with TestClient(app, raise_server_exceptions=False) as client:
        token = paired_token(client, app, user_id)
        for path, params in queries:
            response = client.get(path, params=params, headers=bearer(token))
            assert response.status_code == 422, (path, params, response.status_code)
            assert response.json()["code"] == "validation_error", (path, params)
