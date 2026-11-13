"""`/companion/v1/journal` (Dagbok, D-076): the owner's own writing and changes, and the text of a
source read back, through the same use cases as the MCP tools. No draft, summary or finalize route
exists."""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID, uuid4

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from sidekick.shared.auth import TOKEN_SCOPES
from sidekick.structured.journal import (
    journal_day_structured,
    journal_entries_structured,
    journal_entry_structured,
    journal_source_structured,
    write_journal_entry_structured,
)
from tests.support.companion import (
    FixedClock,
    bearer,
    companion_app,
    owner,
    owner_actor,
    paired_token,
)

DAY = "2026-07-21"
DAY_PATH = f"/companion/v1/journal/days/{DAY}"
ENTRIES = "/companion/v1/journal/entries"
TITLE = "Dagboksrubrik companion-hemlig"
SOURCE = "Dagens anteckning med vanlig text och inga bilder."
SOURCES = "/companion/v1/journal/sources"
READ_ONLY = {"companion:journal:read"}
WRITE_ONLY = {"companion:journal:write"}
TASKS_ONLY = {"companion:tasks:read", "companion:tasks:complete"}
LOG_TITLE = "Titel-hemlig-marker-41"
LOG_SOURCE = "Dagboksrad-hemlig-marker-42"
LOG_POINT = "Punkt-hemlig-marker-43"
IDEM_KEY = "nyckel-hemlig-logg-0001"


def body(title: str = TITLE, source_text: str = SOURCE, **fields: Any) -> dict[str, Any]:
    return {"journal_date": DAY, "title": title, "source_text": source_text, **fields}


def write_headers(token: str, key: str) -> dict[str, str]:
    return {**bearer(token), "Idempotency-Key": key}


def seed(app: FastAPI, user_id: UUID, title: str = TITLE, source_text: str = SOURCE) -> Any:
    """An entry written through the MCP use case, as the owner's own words."""
    return write_journal_entry_structured(
        app.state.container,
        owner_actor(user_id),
        journal_date=date.fromisoformat(DAY),
        title=title,
        source_text=source_text,
        idempotency_key=f"seed-{uuid4()}",
    ).model_dump(mode="json")["entry"]


@pytest.mark.integration
def test_missing_malformed_or_personal_credentials_are_401_on_read_and_write() -> None:
    app = companion_app()
    user_id = owner(app)
    pat = app.state.container.auth.create_personal_token(user_id, "mcp", TOKEN_SCOPES)
    candidates: tuple[dict[str, str], ...] = (
        {},
        {"Authorization": f"Basic {pat}"},
        {"Authorization": "Bearer"},
        bearer(pat),
        bearer("rsc_" + "x" * 40),
    )
    with TestClient(app) as client:
        for headers in candidates:
            read = client.get(DAY_PATH, headers=headers)
            write = client.post(
                ENTRIES, headers={**headers, "Idempotency-Key": "auth-key-0001"}, json=body()
            )
            assert read.status_code == 401, headers
            assert read.json()["code"] == "unauthorized"
            assert write.status_code == 401, headers
            assert write.json()["code"] == "unauthorized"
        token = paired_token(client, app, user_id)
        # Nothing was written by the refused calls.
        assert client.get(DAY_PATH, headers=bearer(token)).json()["entries"] == []


@pytest.mark.integration
def test_missing_journal_capabilities_are_403_capability_missing() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        tasks = paired_token(client, app, user_id, scopes=TASKS_ONLY)
        writer = paired_token(client, app, user_id, scopes=WRITE_ONLY)
        reader = paired_token(client, app, user_id, scopes=READ_ONLY)
        full = paired_token(client, app, user_id)
        for path in (DAY_PATH, ENTRIES, f"{ENTRIES}/{uuid4()}"):
            denied = client.get(path, headers=bearer(tasks))
            assert denied.status_code == 403, path
            assert denied.json()["code"] == "forbidden"
            assert denied.json()["reason"] == "capability_missing"
        # Write without read is refused too: the write also needs `companion:journal:read`.
        assert client.get(DAY_PATH, headers=bearer(writer)).status_code == 403
        assert client.get(DAY_PATH, headers=bearer(reader)).status_code == 200
        for token, key in ((writer, "cap-write-0001"), (reader, "cap-write-0002")):
            created = client.post(ENTRIES, headers=write_headers(token, key), json=body())
            assert created.status_code == 403
            assert created.json()["reason"] == "capability_missing"
            assert TITLE not in created.text
            updated = client.post(
                f"{ENTRIES}/{uuid4()}/update",
                headers=write_headers(token, f"{key}-upd"),
                json={"version": 1, "append_text": "Mer text."},
            )
            assert updated.status_code == 403
            assert updated.json()["reason"] == "capability_missing"
        assert client.get(DAY_PATH, headers=bearer(full)).json()["entries"] == []


@pytest.mark.integration
def test_reads_equal_the_mcp_structured_content_and_refuse_foreign_missing_and_bad_input() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    container = app.state.container
    actor = owner_actor(user_id)
    first = seed(app, user_id, "Första", "Första anteckningen.")
    second = seed(app, user_id, "Andra", "Andra anteckningen.")
    foreign = seed(app, stranger, "Främmande")
    day = date.fromisoformat(DAY)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        day_response = client.get(DAY_PATH, headers=bearer(token))
        assert day_response.status_code == 200
        assert day_response.headers["cache-control"] == "no-store"
        assert day_response.json() == journal_day_structured(
            container,
            actor,
            day,
            include_archived=False,
            include_content=True,
            limit=10,
            cursor=None,
        ).model_dump(mode="json")
        listed_ids = {item["id"] for item in day_response.json()["entries"]}
        assert listed_ids == {first["id"], second["id"]}
        assert str(foreign["id"]) not in day_response.text

        listed = client.get(f"{ENTRIES}?from_date={DAY}&to_date={DAY}", headers=bearer(token))
        assert listed.status_code == 200
        assert listed.json() == journal_entries_structured(
            container,
            actor,
            from_date=day,
            to_date=day,
            include_archived=False,
            include_content=True,
            limit=10,
            cursor=None,
        ).model_dump(mode="json")
        one = client.get(f"{ENTRIES}/{first['id']}", headers=bearer(token))
        assert one.json() == journal_entry_structured(
            container, actor, UUID(first["id"]), include_content=True
        ).model_dump(mode="json")
        assert (one.json()["entry"]["title"], one.json()["entry"]["version"]) == ("Första", 1)

        for path in (f"{ENTRIES}/{foreign['id']}", f"{ENTRIES}/{uuid4()}"):
            missing = client.get(path, headers=bearer(token))
            assert missing.status_code == 404, path
            assert missing.json()["code"] == "not_found"
            assert "Främmande" not in missing.text
        # A day without entries is an empty answer, not a 404.
        empty = client.get("/companion/v1/journal/days/2026-07-22", headers=bearer(token))
        assert empty.status_code == 200
        assert (empty.json()["journal_date"], empty.json()["entries"]) == ("2026-07-22", [])

        bad_day = "/companion/v1/journal/days/2026-13-45"
        assert client.get(bad_day, headers=bearer(token)).status_code == 422
        for query in ("limit=0", "limit=51"):
            for path in (DAY_PATH, ENTRIES):
                response = client.get(f"{path}?{query}", headers=bearer(token))
                assert response.status_code == 422, (path, query)
                assert response.json()["api_version"] == "companion.v1"
        inverted = f"{ENTRIES}?from_date=2026-07-22&to_date={DAY}"
        assert client.get(inverted, headers=bearer(token)).status_code == 422
        assert client.get(f"{ENTRIES}?from_date=nope", headers=bearer(token)).status_code == 422


@pytest.mark.integration
def test_write_creates_one_entry_and_a_retry_with_the_same_key_replays_it() -> None:
    app = companion_app()
    user_id = owner(app)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        headers = write_headers(token, "journal-write-0001")
        created = client.post(ENTRIES, headers=headers, json=body())
        replay = client.post(ENTRIES, headers=headers, json=body())
        other = client.post(ENTRIES, headers=headers, json=body(title="Annan rubrik"))
        day_entries = client.get(DAY_PATH, headers=bearer(token)).json()["entries"]
    assert created.status_code == 200
    entry = created.json()["entry"]
    assert (entry["title"], entry["version"], entry["journal_date"]) == (TITLE, 1, DAY)
    assert replay.json() == created.json()
    assert other.status_code == 409
    assert other.json()["reason"] == "idempotency_key_reused"
    assert "Annan rubrik" not in other.text
    assert [item["id"] for item in day_entries] == [entry["id"]]


@pytest.mark.integration
def test_update_appends_replaces_and_refuses_stale_foreign_and_empty_replace() -> None:
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    entry = seed(app, user_id)
    foreign = seed(app, stranger, "Främmande dagbok")
    entry_path = f"{ENTRIES}/{entry['id']}/update"
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)

        def update(path: str, key: str, payload: dict[str, Any]) -> Any:
            return client.post(path, headers=write_headers(token, key), json=payload)

        appended = update(
            entry_path, "update-append-01", {"version": 1, "append_text": "Mer text."}
        )
        assert appended.status_code == 200
        assert appended.json()["entry"]["id"] == entry["id"]
        assert (appended.json()["entry"]["version"], appended.json()["entry"]["title"]) == (
            2,
            TITLE,
        )

        replaced = update(
            entry_path,
            "update-replace-01",
            {
                "version": 2,
                "title": "Ny rubrik",
                "key_points": [{"kind": "decision", "text": "Jag bestämde mig."}],
            },
        )
        assert replaced.status_code == 200
        assert replaced.json()["entry"]["version"] == 3
        assert replaced.json()["entry"]["title"] == "Ny rubrik"
        assert [point["kind"] for point in replaced.json()["entry"]["key_points"]] == ["decision"]

        stale = update(entry_path, "update-stale-001", {"version": 1, "append_text": "Gammal."})
        assert stale.status_code == 409
        # The journal use case raises a plain stale-version conflict (no closed reason), as for MCP.
        assert stale.json()["code"] == "conflict"
        assert "Gammal" not in stale.text

        foreign_update = update(
            f"{ENTRIES}/{foreign['id']}/update",
            "update-foreign-1",
            {"version": 1, "title": "Kapad", "key_points": []},
        )
        assert foreign_update.status_code == 404
        assert "Kapad" not in foreign_update.text

        # Replace mode needs title and key_points: a null title alone is refused as a validation
        # error (the MCP use case's own ValidationError, mapped to 422 by the route).
        unlabeled = update(entry_path, "update-null-0001", {"version": 3, "title": None})
        assert unlabeled.status_code == 422
        assert unlabeled.json()["code"] == "validation_error"
        unknown = update(
            entry_path,
            "update-extra-0001",
            {"version": 3, "title": "Ny", "key_points": [], "owner_id": str(stranger)},
        )
        assert unknown.status_code == 422
        final = client.get(f"{ENTRIES}/{entry['id']}", headers=bearer(token)).json()["entry"]
        assert (final["version"], final["title"]) == (3, "Ny rubrik")


@pytest.mark.integration
@pytest.mark.parametrize(
    "field", ["add_project_ids", "remove_project_ids", "add_contact_ids", "remove_contact_ids"]
)
def test_update_refuses_link_fields_as_a_plain_422_without_echo(field: str) -> None:
    # Links need projects:read / contacts:read, which a Dagbok device never holds: the route
    # refuses the field up front instead of letting the use case answer 403 after the fact.
    app = companion_app()
    user_id = owner(app)
    entry = seed(app, user_id)
    link = str(uuid4())
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        response = client.post(
            f"{ENTRIES}/{entry['id']}/update",
            headers=write_headers(token, "update-links-0001"),
            json={"version": 1, field: [link]},
        )
        assert response.status_code == 422
        assert response.json()["code"] == "validation_error"
        assert link not in response.text and field not in response.text
        current = client.get(f"{ENTRIES}/{entry['id']}", headers=bearer(token)).json()["entry"]
        assert current["version"] == 1


@pytest.mark.integration
def test_write_bodies_are_strict_capped_and_parsed_only_after_authentication() -> None:
    # An oversized body is refused at ingress by the size ceiling (413) before any auth check, which
    # reads and stores nothing and reveals nothing but the public ceiling. A body within the ceiling
    # is never parsed or written for an unauthenticated caller (401).
    app = companion_app()
    user_id = owner(app)
    oversized = b'{"journal_date": "2026-07-21", "title": "T", "source_text": "' + b"ord " * 70_000
    oversized += b'"}'
    assert len(oversized) > 256 * 1024
    json_type = {"Content-Type": "application/json"}
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        auth = {**bearer(token), "Idempotency-Key": "body-check-0001", **json_type}
        too_big = client.post(ENTRIES, headers=auth, content=oversized)
        assert too_big.status_code == 413
        assert too_big.json()["code"] == "payload_too_large"
        anonymous = client.post(
            ENTRIES, headers={"Idempotency-Key": "body-check-0001", **json_type}, content=oversized
        )
        assert anonymous.status_code == 413
        assert anonymous.json()["code"] == "payload_too_large"
        anonymous_in_cap = client.post(
            ENTRIES, headers={"Idempotency-Key": "body-check-0001", **json_type}, json=body()
        )
        assert anonymous_in_cap.status_code == 401
        assert anonymous_in_cap.json()["code"] == "unauthorized"

        extra = client.post(ENTRIES, headers=auth, json=body(owner_id=str(user_id)))
        assert extra.status_code == 422
        plain = client.post(
            ENTRIES,
            headers={**bearer(token), "Idempotency-Key": "body-check-0001"},
            content=json.dumps(body()).encode(),
        )
        assert plain.status_code == 415
        assert plain.json()["code"] == "unsupported_media_type"
        no_key = client.post(ENTRIES, headers={**bearer(token), **json_type}, json=body())
        assert no_key.status_code == 422
        long_key = client.post(
            ENTRIES,
            headers={**bearer(token), "Idempotency-Key": "k" * 121, **json_type},
            json=body(),
        )
        assert long_key.status_code == 422
        too_long = client.post(ENTRIES, headers=auth, json=body(source_text="x" * 100_001))
        assert too_long.status_code == 422
        assert "xxxxxxxxxx" not in too_long.text

        big_text = "Vanlig text med mellanslag. " * 3300
        assert 90_000 <= len(big_text) <= 100_000
        saved = client.post(
            ENTRIES,
            headers={**bearer(token), "Idempotency-Key": "body-check-0002", **json_type},
            json=body(source_text=big_text),
        )
        assert saved.status_code == 200
        assert saved.json()["entry"]["title"] == TITLE


@pytest.mark.integration
def test_no_log_record_carries_a_journal_title_text_point_token_or_key(
    caplog: pytest.LogCaptureFixture,
) -> None:
    app = companion_app()
    user_id = owner(app)
    caplog.set_level(logging.DEBUG)
    # Sidekick's loggers may not propagate to the root logger; listen on them directly.
    watched = [logging.getLogger(name) for name in ("sidekick", "uvicorn", "fastapi", "fastmcp")]
    for logger in watched:
        logger.addHandler(caplog.handler)
    try:
        token = _exercise_journal(app, user_id)
    finally:
        for logger in watched:
            logger.removeHandler(caplog.handler)
    records = [r for r in caplog.records if not r.name.startswith(("httpx", "httpcore"))]
    operations = {
        getattr(record, "companion_operation", None)
        for record in records
        if record.getMessage() == "companion_request"
    }
    assert {"journal.entry_write", "journal.day", "journal.entry_update", "journal.entry"} <= (
        operations
    )
    for record in records:
        rendered = f"{record.getMessage()} {record.__dict__}"
        for forbidden in (LOG_TITLE, LOG_SOURCE, LOG_POINT, token, IDEM_KEY):
            assert forbidden not in rendered, (record.name, record.getMessage())


def _exercise_journal(app: FastAPI, user_id: UUID) -> str:
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        created = client.post(
            ENTRIES,
            headers=write_headers(token, IDEM_KEY),
            json=body(title=LOG_TITLE, source_text=f"{LOG_SOURCE} " * 3),
        )
        entry_id = created.json()["entry"]["id"]
        client.get(DAY_PATH, headers=bearer(token))
        client.get(f"{ENTRIES}/{entry_id}", headers=bearer(token))
        client.post(
            f"{ENTRIES}/{entry_id}/update",
            headers=write_headers(token, "log-update-0001"),
            json={"version": 1, "append_key_points": [{"kind": "fact", "text": LOG_POINT}]},
        )
        client.get(DAY_PATH, headers=bearer(token + "x"))
    return str(token)


@pytest.mark.integration
def test_draft_summary_and_finalize_routes_do_not_exist() -> None:
    app = companion_app()
    user_id = owner(app)
    entry = seed(app, user_id)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        assert client.get("/companion/v1/journal/drafts", headers=bearer(token)).status_code == 404
        assert client.get("/companion/v1/journal/summary", headers=bearer(token)).status_code == 404
        assert client.get(f"{DAY_PATH}/summary", headers=bearer(token)).status_code == 404
        finalize = f"{ENTRIES}/{entry['id']}/finalize"
        assert (
            client.post(finalize, headers=write_headers(token, "fin-0001"), json={}).status_code
            == 404
        )


@pytest.mark.integration
def test_an_oversize_journal_page_is_shortened_and_marked_never_sent_whole(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sidekick.companion import response_budget

    monkeypatch.setattr(response_budget, "MAX_RESPONSE_BYTES", 5_000)
    app = companion_app()
    user_id = owner(app)
    for number in range(4):
        write_journal_entry_structured(
            app.state.container,
            owner_actor(user_id),
            journal_date=date.fromisoformat(DAY),
            title=f"Rad {number}",
            source_text=SOURCE,
            summary="s" * 1_500,
            idempotency_key=f"big-{number}-{uuid4()}",
        )
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        for path in (DAY_PATH, f"{ENTRIES}?from_date={DAY}&to_date={DAY}"):
            first = client.get(path, headers=bearer(token))
            assert first.status_code == 200, path
            assert len(first.content) <= 5_000
            assert first.headers["sidekick-response-trimmed"] == "page"
            assert 0 < len(first.json()["entries"]) < 4
            assert first.json()["next_cursor"]
        # The cursor continues where the short page ended: nothing is lost or repeated.
        seen: list[str] = []
        cursor: str | None = None
        while True:
            query = f"?cursor={cursor}" if cursor else ""
            page = client.get(DAY_PATH + query, headers=bearer(token))
            assert len(page.content) <= 5_000
            seen += [entry["title"] for entry in page.json()["entries"]]
            cursor = page.json()["next_cursor"]
            if not cursor:
                break
        assert sorted(seen) == [f"Rad {number}" for number in range(4)]


@pytest.mark.integration
def test_a_single_oversize_entry_loses_its_content_and_any_other_oversize_answer_is_a_500(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from sidekick.companion import response_budget

    monkeypatch.setattr(response_budget, "MAX_RESPONSE_BYTES", 2_000)
    app = companion_app()
    user_id = owner(app)
    entry = write_journal_entry_structured(
        app.state.container,
        owner_actor(user_id),
        journal_date=date.fromisoformat(DAY),
        title="Stor rad",
        source_text=SOURCE,
        summary="s" * 3_000,
        idempotency_key=f"single-{uuid4()}",
    ).model_dump(mode="json")["entry"]
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        one = client.get(f"{ENTRIES}/{entry['id']}", headers=bearer(token))
        assert one.status_code == 200
        assert one.headers["sidekick-response-trimmed"] == "content"
        assert (one.json()["entry"]["title"], one.json()["entry"]["summary"]) == ("Stor rad", None)
        monkeypatch.setattr(response_budget, "MAX_RESPONSE_BYTES", 10)
        refused = client.get("/companion/v1/device", headers=bearer(token))
        assert refused.status_code == 500
        assert refused.json()["code"] == "internal_error"
        assert token not in refused.text


@pytest.mark.integration
def test_a_hand_written_entry_can_be_read_back_through_its_source() -> None:
    # A hand-written entry has no summary or key points, so its words live only in the source: the
    # source route answers them, as the MCP tool does, to the owner's own device and no one else.
    app = companion_app()
    user_id = owner(app)
    stranger = owner(app, "stranger")
    foreign = seed(app, stranger, "Främmande", "Främmande källtext.")
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        created = client.post(
            ENTRIES, headers=write_headers(token, "journal-source-0001"), json=body()
        )
        entry = created.json()["entry"]
        assert (entry["summary"], entry["key_points"]) == (None, [])

        source_path = f"{SOURCES}/{entry['source_id']}"
        read = client.get(source_path, headers=bearer(token))
        assert read.status_code == 200
        assert read.headers["cache-control"] == "no-store"
        assert read.json()["source"]["raw_text"] == SOURCE
        assert read.json() == journal_source_structured(
            app.state.container,
            owner_actor(user_id),
            UUID(entry["source_id"]),
            include_content=True,
        ).model_dump(mode="json")
        metadata = client.get(f"{source_path}?include_content=false", headers=bearer(token))
        assert metadata.json()["source"]["raw_text"] is None

        for path in (f"{SOURCES}/{foreign['source_id']}", f"{SOURCES}/{uuid4()}"):
            missing = client.get(path, headers=bearer(token))
            assert missing.status_code == 404, path
            assert missing.json()["code"] == "not_found"
            assert "Främmande" not in missing.text
        assert client.get(f"{SOURCES}/not-a-uuid", headers=bearer(token)).status_code == 422

        # Without the journal read capability the text is not answered.
        tasks = paired_token(client, app, user_id, scopes=TASKS_ONLY)
        denied = client.get(source_path, headers=bearer(tasks))
        assert denied.status_code == 403
        assert denied.json()["reason"] == "capability_missing"
        assert SOURCE not in denied.text
        assert client.get(source_path).status_code == 401


@pytest.mark.parametrize(
    ("now", "owner_day"),
    [
        # 23:30 UTC on 4 November is 00:30 on the 5th in Stockholm (winter time).
        (datetime(2026, 11, 4, 23, 30, tzinfo=UTC), "2026-11-05"),
        (datetime(2026, 11, 4, 22, 30, tzinfo=UTC), "2026-11-04"),
        # The night the clocks go forward: Stockholm is still UTC+1 until 01:00 UTC.
        (datetime(2026, 3, 28, 22, 30, tzinfo=UTC), "2026-03-28"),
        (datetime(2026, 3, 28, 23, 0, tzinfo=UTC), "2026-03-29"),
        # The night they go back: 22:30 UTC on 24 October is 00:30 on the 25th (summer time).
        (datetime(2026, 10, 24, 22, 30, tzinfo=UTC), "2026-10-25"),
    ],
)
def test_day_and_default_list_carry_the_owners_zone_and_todays_date_for_the_phone(
    now: datetime, owner_day: str
) -> None:
    app = companion_app()
    user_id = owner(app)
    app.state.container.journal.clock = FixedClock(now)
    with TestClient(app) as client:
        token = paired_token(client, app, user_id)
        day = client.get(DAY_PATH, headers=bearer(token))
        listed = client.get(ENTRIES, headers=bearer(token))

    assert day.status_code == listed.status_code == 200
    for payload in (day.json(), listed.json()):
        assert payload["owner_timezone"] == "Europe/Stockholm"
        assert payload["today"] == owner_day
