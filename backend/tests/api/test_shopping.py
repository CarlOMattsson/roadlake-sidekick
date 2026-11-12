"""Shopping transactions, authorization and the MCP transport against PostgreSQL."""

import logging
from collections.abc import Iterator
from datetime import date
from uuid import UUID

import httpx
import pytest
from fastmcp import Client
from fastmcp.client.transports import StreamableHttpTransport
from sqlalchemy import select, text
from sqlalchemy.exc import DBAPIError

from sidekick.api.app import create_app
from sidekick.contacts.application.service import CreateContactCommand
from sidekick.owner_export.core import OwnerExportService, build_restore_plan
from sidekick.shared.auth import ALL_SCOPES
from sidekick.shared.errors import ConflictError, NotFoundError, PermissionDeniedError
from sidekick.shared.types import Actor, new_uuid7
from sidekick.shopping.application.schemas import BatchItem, ItemInput
from sidekick.shopping.application.service import LOGGER as SHOPPING_LOGGER
from sidekick.shopping.persistence.rows import ShoppingStatusRow
from sidekick.store import SqlAlchemyStore
from tests.db import database_factory
from tests.support.settings import make_settings


class _Collector(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.INFO)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture(name="shopping_logs")
def _shopping_logs() -> Iterator[_Collector]:
    """Attach directly to the shopping logger instead of relying on `caplog`.

    `configure_observability` (run by `create_app`) sets `propagate = False` on the
    `sidekick` logger, so records never reach the root handler `caplog` listens on.
    Same pattern and rationale as `tests/contract/test_chat_provider_status_logging.py`.
    """

    collector = _Collector()
    SHOPPING_LOGGER.addHandler(collector)
    previous = SHOPPING_LOGGER.level
    SHOPPING_LOGGER.setLevel(logging.INFO)
    try:
        yield collector
    finally:
        SHOPPING_LOGGER.removeHandler(collector)
        SHOPPING_LOGGER.setLevel(previous)


def setup():
    factory = database_factory()
    app = create_app(make_settings(), factory)
    c = app.state.container
    owner = c.auth.provision_user("shop-owner", "Owner")
    other = c.auth.provision_user("shop-other", "Other")
    actor = Actor(owner, ALL_SCOPES)
    second = Actor(other, ALL_SCOPES)
    return factory, app, c, actor, second, owner, other


@pytest.mark.integration
def test_batch_replay_versions_purchase_history_and_owner_export():
    factory, _, c, actor, _, _, _ = setup()
    service = c.shopping
    shopping = service.create_list(actor, "IKEA someday", idempotency_key="create-list-1")
    list_id = UUID(shopping["shopping_list"]["id"])
    inputs = [
        BatchItem(name="Shelf", store="IKEA", client_ref="shelf"),
        BatchItem(name="Birthday idea", occasion="Birthday", client_ref="gift"),
    ]
    added = service.add_items(actor, list_id, inputs, idempotency_key="add-batch-1")
    assert service.add_items(actor, list_id, inputs, idempotency_key="add-batch-1") == added
    assert [i["client_ref"] for i in added["items"]] == ["shelf", "gift"]
    assert added["items"][0]["item"]["target_date"] is None
    first = added["items"][0]["item"]
    item_id = UUID(first["id"])
    purchased = service.set_purchased(
        actor, item_id, purchased=True, version=1, idempotency_key="purchase-1"
    )
    assert (
        service.set_purchased(
            actor, item_id, purchased=True, version=1, idempotency_key="purchase-1"
        )
        == purchased
    )
    assert purchased["item"]["purchased_at"] and purchased["item"]["version"] == 2
    with pytest.raises(ConflictError):
        service.set_purchased(
            actor, item_id, purchased=False, version=1, idempotency_key="stale-purchase"
        )
    service.set_purchased(actor, item_id, purchased=False, version=2, idempotency_key="reopen-1")
    with factory() as session:
        history = list(
            session.scalars(select(ShoppingStatusRow).order_by(ShoppingStatusRow.item_version))
        )
        assert [(r.purchased, r.item_version) for r in history] == [(True, 2), (False, 3)]
        with pytest.raises(DBAPIError):
            session.execute(text("DELETE FROM sidekick.shopping_item_status_history"))
    document = OwnerExportService(SqlAlchemyStore(factory)).export(actor)
    assert len(document["collections"]["shopping_items"]) == 2
    assert len(document["collections"]["shopping_item_status_history"]) == 2
    assert build_restore_plan(document, new_uuid7()).status == "ready"
    with pytest.raises(ConflictError):
        service.add_items(
            actor,
            list_id,
            [BatchItem(name="Different", client_ref="a")],
            idempotency_key="add-batch-1",
        )


@pytest.mark.integration
def test_purchase_again_with_stale_version_is_unchanged_but_a_real_change_still_conflicts():
    factory, _, c, actor, _, _, _ = setup()
    service = c.shopping
    shopping = service.create_list(actor, "Handla", idempotency_key="create-list-stale")
    list_id = UUID(shopping["shopping_list"]["id"])
    added = service.add_items(
        actor,
        list_id,
        [BatchItem(name="Mjölk", client_ref="milk")],
        idempotency_key="add-milk-stale",
    )
    milk = UUID(added["items"][0]["item"]["id"])
    first = service.set_purchased(
        actor, milk, purchased=True, version=1, idempotency_key="milk-buy-first"
    )
    assert first["unchanged"] is False
    assert first["item"]["version"] == 2
    # Bought again with the version from before (ticked in the card meanwhile): no error, no write.
    again = service.set_purchased(
        actor, milk, purchased=True, version=1, idempotency_key="milk-buy-again"
    )
    assert again["unchanged"] is True
    assert again["item"]["version"] == 2
    assert again["item"]["purchased_at"] == first["item"]["purchased_at"]
    # A real change with the old version still conflicts, and writes nothing.
    with pytest.raises(ConflictError):
        service.set_purchased(
            actor, milk, purchased=False, version=1, idempotency_key="milk-back-stale"
        )
    with factory() as session:
        history = list(
            session.scalars(select(ShoppingStatusRow).where(ShoppingStatusRow.item_id == milk))
        )
        assert [(r.purchased, r.item_version) for r in history] == [(True, 2)]


@pytest.mark.integration
def test_foreign_contact_rejects_whole_batch_and_scopes_apply_before_replay():
    _, _, c, actor, second, _, _ = setup()
    own = UUID(
        c.shopping.create_list(actor, "Gifts", idempotency_key="create-gifts")["shopping_list"][
            "id"
        ]
    )
    contact = c.contacts.create(
        second,
        CreateContactCommand(display_name="Other's contact"),
        idempotency_key="foreign-contact",
    )
    items = [
        BatchItem(name="Valid", client_ref="a"),
        BatchItem(name="Foreign", recipient_contact_id=contact.id, client_ref="b"),
    ]
    with pytest.raises(NotFoundError):
        c.shopping.add_items(actor, own, items, idempotency_key="atomic-batch")
    assert c.shopping.get_list(actor, own)["items"] == []
    with pytest.raises(NotFoundError):
        c.shopping.get_list(second, own)
    reader = Actor(actor.user_id, frozenset({"shopping:read"}))
    with pytest.raises(PermissionDeniedError):
        c.shopping.add_items(
            reader,
            own,
            [BatchItem(name="No write", client_ref="a")],
            idempotency_key="denied-write",
        )
    owned_contact = c.contacts.create(
        actor,
        CreateContactCommand(display_name="Chosen recipient"),
        idempotency_key="owned-contact",
    )
    good = [BatchItem(name="Gift", client_ref="a", recipient_contact_id=owned_contact.id)]
    c.shopping.add_items(actor, own, good, idempotency_key="owned-gift")
    no_contacts = Actor(actor.user_id, frozenset({"shopping:read", "shopping:write"}))
    with pytest.raises(PermissionDeniedError):
        c.shopping.add_items(no_contacts, own, good, idempotency_key="owned-gift")
    archived = c.shopping.update_list(
        actor, own, name="Gifts", archived=True, version=1, idempotency_key="archive-gifts"
    )
    assert archived["shopping_list"]["archived"]
    with pytest.raises(ConflictError):
        c.shopping.add_items(actor, own, good, idempotency_key="archived-write")


@pytest.mark.integration
def test_offer_expiry_and_pagination_are_derived_on_read():
    _, _, c, actor, _, _, _ = setup()
    list_id = UUID(
        c.shopping.create_list(actor, "Weekly", idempotency_key="weekly-list")["shopping_list"][
            "id"
        ]
    )
    item = BatchItem(
        client_ref="a",
        name="Recorded offer",
        store="Store",
        offer={
            "price": "49.90",
            "regular_price": "69.90",
            "valid_from": "2026-10-19",
            "valid_until": "2026-10-25",
            "checked_on": "2026-10-19",
            "source": "Leaflet",
        },
    )
    c.shopping.add_items(
        actor,
        list_id,
        [item, BatchItem(client_ref="b", name="Next")],
        idempotency_key="weekly-batch",
    )
    current = c.shopping.get_list(actor, list_id, on_date=date(2026, 10, 25), limit=1)
    assert current["items"][0]["offer_status"] == "current"
    assert current["next_offset"] == 1
    assert (
        c.shopping.get_list(actor, list_id, on_date=date(2026, 10, 26))["items"][0]["offer_status"]
        == "expired"
    )
    assert c.shopping.get_list(actor, list_id, offset=1, limit=1)["items"][0]["name"] == "Next"


@pytest.mark.integration
def test_a_batch_keeps_its_submitted_order_on_read():
    _, _, c, actor, _, _, _ = setup()
    list_id = UUID(
        c.shopping.create_list(actor, "Ordered", idempotency_key="ordered-list")["shopping_list"][
            "id"
        ]
    )
    names = [f"Item {number:02d}" for number in range(30)]
    c.shopping.add_items(
        actor,
        list_id,
        [BatchItem(client_ref=name.replace(" ", "-"), name=name) for name in names],
        idempotency_key="ordered-batch",
    )
    read = c.shopping.get_list(actor, list_id, limit=100)
    assert [item["name"] for item in read["items"]] == names


@pytest.mark.integration
@pytest.mark.asyncio
async def test_authenticated_mcp_app_resource_and_oversized_batch():
    _, app, c, actor, _, owner, _ = setup()
    token = c.auth.create_personal_token(
        owner, "Shopping test", frozenset({"shopping:read", "shopping:write"})
    )

    def client_factory(**kwargs):
        return httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://testserver", **kwargs
        )

    transport = StreamableHttpTransport(
        "http://testserver/mcp/",
        headers={"Authorization": f"Bearer {token}"},
        httpx_client_factory=client_factory,
    )
    async with app.router.lifespan_context(app), Client(transport) as client:
        created = await client.call_tool(
            "create_shopping_list", {"name": "MCP and web", "idempotency_key": "transport-create"}
        )
        list_id = created.structured_content["shopping_list"]["id"]
        added = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [{"client_ref": "a", "name": "Both interfaces"}],
                "idempotency_key": "transport-batch",
            },
        )
        assert len(added.structured_content["items"]) == 1
        tools = await client.list_tools()
        tool = next(t for t in tools if t.name == "get_shopping_list")
        assert tool.meta["ui"]["resourceUri"] == "ui://sidekick/app-v1.html"
        resource = await client.read_resource("ui://sidekick/app-v1.html")
        assert resource[0].mimeType == "text/html;profile=mcp-app"
        assert "<script>" in resource[0].text and "Both interfaces" not in resource[0].text
        denied = await client.call_tool(
            "get_shopping_list", {"list_id": str(new_uuid7())}, raise_on_error=False
        )
        assert denied.is_error and denied.structured_content["code"] == "not_found"
        oversized = await client.call_tool(
            "add_shopping_items",
            {
                "list_id": list_id,
                "items": [{"name": "item", "client_ref": str(i)} for i in range(51)],
                "idempotency_key": "oversized-batch",
            },
            raise_on_error=False,
        )
        assert oversized.is_error
    assert len(c.shopping.get_list(actor, UUID(list_id))["items"]) == 1


@pytest.mark.integration
def test_linked_gift_blocks_contact_purge_until_explicit_unlink(shopping_logs: _Collector):
    from sidekick.lifecycle.domain import RecordKind
    from sidekick.shared.observability import safe_telemetry_attributes

    factory, _, c, actor, second, _, _ = setup()
    contact = c.contacts.create(
        actor, CreateContactCommand(display_name="Gift recipient"), "create-recipient"
    )
    list_id = UUID(
        c.shopping.create_list(actor, "Gift ideas", idempotency_key="gift-ideas-list")[
            "shopping_list"
        ]["id"]
    )
    added = c.shopping.add_items(
        actor,
        list_id,
        [
            BatchItem(
                client_ref="gift", name="PRIVATE_SHOPPING_CONTENT", recipient_contact_id=contact.id
            )
        ],
        idempotency_key="gift-for-person",
        correlation_id="shopping-test-correlation",
    )
    item_id = UUID(added["items"][0]["item"]["id"])
    trashed = c.lifecycle.trash(
        actor,
        RecordKind.CONTACT,
        contact.id,
        version=contact.version,
        idempotency_key="trash-gift-person",
    )
    with pytest.raises(ConflictError):
        c.lifecycle.permanently_remove(
            actor,
            RecordKind.CONTACT,
            contact.id,
            version=trashed.version,
            idempotency_key="purge-linked-gift",
        )
    with pytest.raises(NotFoundError):
        c.shopping.update_item(
            second,
            item_id,
            ItemInput(name="Overwrite").domain(),
            version=1,
            idempotency_key="cross-owner-edit",
        )
    updated = c.shopping.update_item(
        actor,
        item_id,
        ItemInput(name="Keep idea", store="IKEA").domain(),
        version=1,
        idempotency_key="unlink-gift-person",
    )
    assert updated["item"]["recipient_contact_id"] is None
    assert (
        c.shopping.update_item(
            actor,
            item_id,
            ItemInput(name="Keep idea", store="IKEA").domain(),
            version=1,
            idempotency_key="unlink-gift-person",
        )
        == updated
    )
    c.lifecycle.permanently_remove(
        actor,
        RecordKind.CONTACT,
        contact.id,
        version=trashed.version,
        idempotency_key="purge-unlinked-gift",
    )
    with pytest.raises(DBAPIError), factory.begin() as session:
        session.execute(
            text("UPDATE sidekick.shopping_items SET offer_source = 'partial' WHERE id = :id"),
            {"id": item_id},
        )
    records = shopping_logs.records
    assert records, "shopping operations must emit structured log records"
    assert any(
        getattr(record, "correlation_id", None) == "shopping-test-correlation" for record in records
    ), "the caller's correlation ID must reach the shopping log record"
    serialized = repr([record.__dict__ for record in records])
    assert "PRIVATE_SHOPPING_CONTENT" not in serialized
    assert "Gift recipient" not in serialized and str(contact.id) not in serialized
    assert safe_telemetry_attributes(
        {
            "shopping.operation": "add_items",
            "shopping.name": "PRIVATE_SHOPPING_CONTENT",
            "shopping.recipient": str(contact.id),
        }
    ) == {"shopping.operation": "add_items"}
