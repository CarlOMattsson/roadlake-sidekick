"""The app-only Journal photo tools: add, get, update, trash and restore, through the real server.

The tools take the photo as base64 and are listed to the app only, never to a model. They call the
same use case as the companion upload. Synthetic images only.
"""

import base64
import logging
from datetime import UTC, date, datetime
from typing import Any
from uuid import uuid4

import pytest

from sidekick.api.app import Container, create_container
from sidekick.journal.domain.entry import KeyPoint, KeyPointKind
from sidekick.journal.domain.source import SourceType
from sidekick.mcp.change_source import REQUIRES_APP_META, requires_app
from sidekick.mcp.journal_photo_tools import JOURNAL_PHOTO_TOOL_NAMES
from sidekick.shared.types import Actor
from tests.db import database_factory
from tests.mcp.harness import SwitchableServer
from tests.support import photo_files
from tests.support.app_origin import APP_ONLY_CALLS, APP_ORIGIN
from tests.support.settings import make_settings

WRITE = frozenset({"journal:read", "journal:write"})
READ = frozenset({"journal:read"})
WRITE_ONLY = frozenset({"journal:write"})
ALT = "Alt-text-hemlig-marker-81"
CAMERA = "Kamera-hemlig-marker-82"
PLACE = "Plats-hemlig-marker-83"


def b64(data: bytes) -> str:
    return base64.b64encode(data).decode()


PHOTO = b64(photo_files.jpeg())
THUMB = b64(photo_files.jpeg(320, 240))


class World:
    def __init__(self) -> None:
        self.container: Container = create_container(make_settings(), database_factory())
        self.owner = self.container.auth.provision_user("mcp-photo-owner", "Owner")
        self.other = self.container.auth.provision_user("mcp-photo-other", "Other")
        self.actor = Actor(self.owner, WRITE)
        self.other_actor = Actor(self.other, WRITE)
        self.entry_id = str(self.entry_of(self.actor).id)
        self.server = SwitchableServer.build(self.container, self.actor)

    def entry_of(self, actor: Actor) -> Any:
        _, entry = self.container.journal_capture.write_entry(
            actor,
            source_type=SourceType.TRANSCRIPT_TEXT,
            journal_date=date(2026, 11, 22),
            occurred_at=datetime(2026, 11, 22, 9, tzinfo=UTC),
            raw_text="Synthetic source text",
            language="sv",
            title="Synthetic entry",
            summary=None,
            key_points=(KeyPoint(KeyPointKind.FACT, "A synthetic fact."),),
            idempotency_key=f"entry-{uuid4().hex}",
        )
        return entry

    async def call(
        self,
        actor: Actor,
        name: str,
        arguments: dict[str, Any],
        meta: dict[str, str] | None = APP_ORIGIN,
    ) -> Any:
        """The call as the app makes it; `meta=None` is a model's call, which carries no mark."""

        async with self.server.client(actor) as client:
            return await client.call_tool(name, arguments, meta=meta, raise_on_error=False)

    async def add(self, actor: Actor | None = None, **fields: Any) -> Any:
        arguments = {
            "photo": PHOTO,
            "thumbnail": THUMB,
            "idempotency_key": f"add-{uuid4().hex}",
            "entry_id": self.entry_id,
            **fields,
        }
        return await self.call(actor or self.actor, "add_journal_photo", arguments)


@pytest.fixture(scope="module")
def world() -> World:
    return World()


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_photo_tools_are_listed_to_the_app_only() -> None:
    server = SwitchableServer.build(
        create_container(make_settings(), database_factory()), Actor(uuid4(), WRITE)
    )
    tools = {tool.name: tool for tool in await server.server.list_tools()}

    for name in JOURNAL_PHOTO_TOOL_NAMES:
        assert (tools[name].meta or {}).get("ui", {}).get("visibility") == ["app"], name


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_photo_is_added_read_back_changed_trashed_and_restored(world: World) -> None:
    added = await world.add(
        alt_text=ALT,
        taken_at="2026-07-04T15:30:00",
        location={"lat": 59.3293, "lon": 18.0686, "name": PLACE},
        camera=CAMERA,
        orientation=6,
    )
    assert not added.is_error, added.content
    photo = added.structured_content["photo"]
    assert photo["entry_id"] == world.entry_id and photo["journal_date"] is None
    assert (photo["alt_text"], photo["alt_text_by"], photo["camera"]) == (ALT, "you", CAMERA)
    assert photo["location"] == {"lat": 59.3293, "lon": 18.0686, "name": PLACE}
    assert photo["orientation"] == 6 and photo["version"] == 1
    # A time sent without an offset is read in the owner's zone and shown in it.
    assert photo["taken_at"].startswith("2026-07-04T15:30:00")
    # Nothing in the record or the model's text shows a digest or the bytes.
    assert "digest" not in str(added.structured_content)
    assert PHOTO not in str(added.content) and THUMB not in str(added.content)

    thumb = await world.call(world.actor, "get_journal_photo", {"photo_id": photo["id"]})
    assert thumb.structured_content["size"] == "thumb"
    assert thumb.structured_content["data"] == THUMB
    full = await world.call(
        world.actor, "get_journal_photo", {"photo_id": photo["id"], "size": "photo"}
    )
    assert full.structured_content["data"] == PHOTO
    assert full.content[0].text == "Returned the photo."

    moved = await world.call(
        world.actor,
        "update_journal_photo",
        {
            "photo_id": photo["id"],
            "changes": {"location": {"lat": 1.5, "lon": 2.5}},
            "expected_version": 1,
            "idempotency_key": f"upd-{uuid4().hex}",
        },
    )
    assert moved.structured_content["photo"]["location"] == {"lat": 1.5, "lon": 2.5, "name": None}
    assert moved.structured_content["photo"]["camera"] == CAMERA

    removed = await world.call(
        world.actor,
        "update_journal_photo",
        {
            "photo_id": photo["id"],
            "changes": {},
            "clear": ["location", "camera"],
            "expected_version": 2,
            "idempotency_key": f"clr-{uuid4().hex}",
        },
    )
    kept = removed.structured_content["photo"]
    assert (kept["location"], kept["camera"], kept["version"]) == (None, None, 3)
    assert kept["alt_text"] == ALT and kept["orientation"] == 6

    trashed = await world.call(
        world.actor,
        "trash_journal_photo",
        {"photo_id": photo["id"], "expected_version": 3, "idempotency_key": f"tr-{uuid4().hex}"},
    )
    assert trashed.structured_content == {"id": photo["id"], "in_trash": True, "version": 4}
    gone = await world.call(world.actor, "get_journal_photo", {"photo_id": photo["id"]})
    assert gone.is_error

    back = await world.call(
        world.actor,
        "restore_journal_photo",
        {"photo_id": photo["id"], "expected_version": 4, "idempotency_key": f"rs-{uuid4().hex}"},
    )
    assert back.structured_content == {"id": photo["id"], "in_trash": False, "version": 5}
    again = await world.call(world.actor, "get_journal_photo", {"photo_id": photo["id"]})
    assert not again.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_refused_file_is_answered_with_its_reason_and_nothing_of_the_file(
    world: World,
) -> None:
    with_gps = await world.add(photo=b64(photo_files.gps_jpeg()))
    assert with_gps.is_error
    assert "carries_metadata" in str(with_gps.content)

    junk = await world.add(photo=b64(b"not an image at all"))
    assert junk.is_error and "unrecognised_type" in str(junk.content)

    broken = await world.add(photo="@@@@not-base64@@@@")
    assert broken.is_error and "malformed" in str(broken.content)


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_target_that_is_not_the_owners_or_two_targets_or_none_are_refused(
    world: World,
) -> None:
    foreign = await world.add(world.other_actor)
    assert foreign.is_error
    two = await world.add(journal_date="2026-11-22")
    assert two.is_error
    neither = await world.call(
        world.actor,
        "add_journal_photo",
        {"photo": PHOTO, "thumbnail": THUMB, "idempotency_key": f"n-{uuid4().hex}"},
    )
    assert neither.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_scopes_of_each_tool_are_checked_by_the_server(world: World) -> None:
    added = await world.add()
    photo_id = added.structured_content["photo"]["id"]

    denied_add = await world.add(Actor(world.owner, READ))
    assert denied_add.is_error
    denied_get = await world.call(
        Actor(world.owner, WRITE_ONLY), "get_journal_photo", {"photo_id": photo_id}
    )
    assert denied_get.is_error
    denied_update = await world.call(
        Actor(world.owner, READ),
        "update_journal_photo",
        {
            "photo_id": photo_id,
            "changes": {"camera": "x"},
            "expected_version": 1,
            "idempotency_key": f"d-{uuid4().hex}",
        },
    )
    assert denied_update.is_error
    foreign_get = await world.call(world.other_actor, "get_journal_photo", {"photo_id": photo_id})
    assert foreign_get.is_error
    foreign_trash = await world.call(
        world.other_actor,
        "trash_journal_photo",
        {"photo_id": photo_id, "expected_version": 1, "idempotency_key": f"f-{uuid4().hex}"},
    )
    assert foreign_trash.is_error
    still = await world.call(world.actor, "get_journal_photo", {"photo_id": photo_id})
    assert not still.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_stale_version_conflicts_and_an_edit_without_a_field_is_refused(
    world: World,
) -> None:
    added = await world.add()
    photo_id = added.structured_content["photo"]["id"]

    stale = await world.call(
        world.actor,
        "update_journal_photo",
        {
            "photo_id": photo_id,
            "changes": {"camera": "Pixel"},
            "expected_version": 9,
            "idempotency_key": f"s-{uuid4().hex}",
        },
    )
    assert stale.is_error
    nothing = await world.call(
        world.actor,
        "update_journal_photo",
        {
            "photo_id": photo_id,
            "changes": {},
            "expected_version": 1,
            "idempotency_key": f"e-{uuid4().hex}",
        },
    )
    assert nothing.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_text_field_with_image_data_is_refused(world: World) -> None:
    refused = await world.add(alt_text="data:image/jpeg;base64," + PHOTO[:120])
    assert refused.is_error


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_retried_add_stores_one_photo(world: World) -> None:
    key = f"retry-{uuid4().hex}"
    first = await world.add(idempotency_key=key)
    again = await world.add(idempotency_key=key)

    assert first.structured_content["photo"]["id"] == again.structured_content["photo"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_no_field_or_byte_reaches_the_logs(
    world: World, caplog: pytest.LogCaptureFixture
) -> None:
    with caplog.at_level(logging.DEBUG):
        added = await world.add(
            alt_text=ALT,
            location={"lat": 59.3293, "lon": 18.0686, "name": PLACE},
            camera=CAMERA,
        )
        await world.call(
            world.actor,
            "get_journal_photo",
            {"photo_id": added.structured_content["photo"]["id"], "size": "photo"},
        )
        await world.add(photo=b64(photo_files.gps_jpeg()), alt_text=ALT)

    logged = "\n".join(
        record.getMessage() + str(getattr(record, "__dict__", "")) for record in caplog.records
    )
    for secret in (ALT, CAMERA, PLACE, "59.3293", "18.0686", PHOTO[:60], THUMB[:60]):
        assert secret not in logged, secret


@pytest.mark.asyncio
@pytest.mark.integration
async def test_a_model_call_to_any_photo_tool_is_refused_as_app_only_and_changes_nothing(
    world: World,
) -> None:
    added = await world.add()
    photo = added.structured_content["photo"]
    arguments: dict[str, dict[str, Any]] = {
        "add_journal_photo": {
            "entry_id": world.entry_id,
            "photo": PHOTO,
            "thumbnail": THUMB,
            "idempotency_key": f"model-{uuid4().hex}",
        },
        "get_journal_photo": {"photo_id": photo["id"], "size": "photo"},
        "update_journal_photo": {
            "photo_id": photo["id"],
            "changes": {"camera": "Model"},
            "expected_version": photo["version"],
            "idempotency_key": f"model-{uuid4().hex}",
        },
        "trash_journal_photo": {
            "photo_id": photo["id"],
            "expected_version": photo["version"],
            "idempotency_key": f"model-{uuid4().hex}",
        },
        "restore_journal_photo": {
            "photo_id": photo["id"],
            "expected_version": photo["version"],
            "idempotency_key": f"model-{uuid4().hex}",
        },
    }
    assert set(arguments) == set(JOURNAL_PHOTO_TOOL_NAMES)

    for name, tool_arguments in arguments.items():
        refused = await world.call(world.actor, name, tool_arguments, meta=None)
        assert refused.is_error, name
        assert refused.structured_content["code"] == "forbidden", name
        assert refused.structured_content["reason"] == "app_only", name
        assert PHOTO not in str(refused.content) and THUMB not in str(refused.content)

    # Nothing changed: the photo is still there, at its version, with no camera.
    again = await world.call(world.actor, "get_journal_photo", {"photo_id": photo["id"]})
    assert again.structured_content["photo"]["version"] == photo["version"]
    assert again.structured_content["photo"]["camera"] is None
    assert photo["id"] in again.structured_content["photo"]["id"]


@pytest.mark.asyncio
@pytest.mark.integration
async def test_the_server_marks_every_photo_tool_as_needing_the_app_by_its_metadata() -> None:
    server = SwitchableServer.build(create_container(make_settings()), Actor(uuid4(), WRITE))
    tools = await server.server.list_tools()

    marked = {tool.name for tool in tools if requires_app(tool.meta)}
    assert marked == APP_ONLY_CALLS
    assert set(JOURNAL_PHOTO_TOOL_NAMES) <= marked
    for tool in tools:
        if tool.name in JOURNAL_PHOTO_TOOL_NAMES:
            assert (tool.meta or {})[REQUIRES_APP_META] is True
