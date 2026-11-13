"""Shopping application use cases shared by HTTP, MCP and the interactive app."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal
from typing import Any, TypedDict, cast
from uuid import UUID, uuid4

from pydantic import BaseModel

from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.idempotent_operation import run_idempotent_operation
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.types import (
    UNSET,
    Actor,
    Clock,
    TxSession,
    UnsetType,
    new_uuid7,
    paginate,
    validate_limit,
)
from sidekick.shopping.application.schemas import (
    AddedItem,
    BatchItem,
    BatchResult,
    ItemRecord,
    ItemResult,
    ListDetail,
    ListRecord,
    ListResult,
    ListsResult,
    ListSummary,
    OfferInput,
    PurchasedBatchResult,
    PurchaseOutcome,
    PurchaseTarget,
)
from sidekick.shopping.domain import ItemDetails, Offer, required_text, text
from sidekick.shopping.persistence.rows import ShoppingItemRow, ShoppingListRow, ShoppingStatusRow
from sidekick.shopping.persistence.store import ShoppingStore

LOGGER = logging.getLogger("sidekick.shopping")
DETAIL_FIELDS = (
    "name",
    "quantity",
    "unit",
    "note",
    "store",
    "product_url",
    "recipient_contact_id",
    "occasion",
    "target_date",
)
OFFER_FIELDS = (
    "price",
    "regular_price",
    "currency",
    "source",
    "source_url",
    "valid_from",
    "valid_until",
    "checked_on",
)
ITEM_FIELDS = (*DETAIL_FIELDS, "offer")

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)


MAX_QUANTITY = Decimal("999999.999")


def _merge_key(name: str, unit: str | None) -> tuple[str, str]:
    """Name and unit as compared by merge_duplicates: case-insensitive, no unit equals no unit."""

    return (name.casefold(), (unit or "").casefold())


class IdRef(TypedDict):
    id: str


class ListReplay(TypedDict):
    shopping_list: IdRef


class ItemReplay(TypedDict):
    item: IdRef


class PurchaseReplay(ItemReplay):
    unchanged: bool


class AddedItemReplay(TypedDict):
    item: IdRef
    merged: bool


class BatchReplay(TypedDict):
    items: list[AddedItemReplay]


class PurchasedBatchReplay(TypedDict):
    items: list[IdRef]
    unchanged_item_ids: list[str]


def _ref(record_id: UUID) -> IdRef:
    return {"id": str(record_id)}


@dataclass(frozen=True, slots=True)
class ItemPatch:
    """Editable item fields. UNSET means the caller did not send the field; None clears it."""

    name: str | UnsetType = UNSET
    quantity: Decimal | UnsetType = UNSET
    unit: str | None | UnsetType = UNSET
    note: str | None | UnsetType = UNSET
    store: str | None | UnsetType = UNSET
    product_url: str | None | UnsetType = UNSET
    recipient_contact_id: UUID | None | UnsetType = UNSET
    occasion: str | None | UnsetType = UNSET
    target_date: date | None | UnsetType = UNSET
    offer: Offer | None | UnsetType = UNSET

    @classmethod
    def full(cls, details: ItemDetails) -> "ItemPatch":
        return cls(**{key: getattr(details, key) for key in ITEM_FIELDS})

    def changes(self) -> dict[str, object]:
        return {key: getattr(self, key) for key in ITEM_FIELDS if getattr(self, key) is not UNSET}

    def payload(self) -> dict[str, object]:
        return {
            key: asdict(value) if isinstance(value, Offer) else value
            for key, value in self.changes().items()
        }


def merged_details(row: ShoppingItemRow, patch: ItemPatch) -> ItemDetails:
    """The stored item with only the patched fields replaced."""

    current = ItemDetails(
        **{key: getattr(row, key) for key in DETAIL_FIELDS},
        offer=(
            Offer(**{key: getattr(row, f"offer_{key}") for key in OFFER_FIELDS})
            if row.offer_price is not None
            else None
        ),
    )
    return replace(current, **patch.changes())


def list_record(row: ShoppingListRow) -> ListRecord:
    return ListRecord.model_validate(row, from_attributes=True)


def item_record(row: ShoppingItemRow, on_date: date, names: Mapping[UUID, str]) -> ItemRecord:
    offer = (
        None
        if row.offer_price is None
        else OfferInput.model_validate({key: getattr(row, f"offer_{key}") for key in OFFER_FIELDS})
    )
    status = "none"
    if offer is not None:
        status = Offer(**offer.model_dump()).status(on_date)
    return ItemRecord(
        **{key: getattr(row, key) for key in DETAIL_FIELDS},
        id=row.id,
        list_id=row.list_id,
        purchased=row.purchased,
        purchased_at=row.purchased_at,
        version=row.version,
        created_at=row.created_at,
        updated_at=row.updated_at,
        offer=offer,
        offer_status=status,
        recipient_contact_name=(
            names.get(row.recipient_contact_id) if row.recipient_contact_id is not None else None
        ),
    )


def _list_replay(result: ListResult) -> ListReplay:
    return {"shopping_list": _ref(result.shopping_list.id)}


def _item_replay(result: ItemResult) -> ItemReplay:
    return {"item": _ref(result.item.id)}


def _purchase_replay(result: PurchaseOutcome) -> PurchaseReplay:
    return {"item": _ref(result.item.id), "unchanged": result.unchanged}


def _purchased_batch_replay(result: PurchasedBatchResult) -> PurchasedBatchReplay:
    return {
        "items": [_ref(item.id) for item in result.items],
        "unchanged_item_ids": [str(item_id) for item_id in result.unchanged_item_ids],
    }


def _added_items_replay(result: BatchResult) -> BatchReplay:
    """What a retry of `add_items` keeps: each item's id and whether it was merged."""

    return {
        "items": [{"item": _ref(entry.item.id), "merged": entry.merged} for entry in result.items]
    }


class ShoppingService:
    def __init__(
        self,
        store: ShoppingStore,
        clock: Clock,
        telemetry: TelemetryPort,
        *,
        owner_timezone: tzinfo = DEFAULT_OWNER_ZONE,
    ) -> None:
        self.store, self.clock, self.telemetry = store, clock, telemetry
        self.owner_timezone = owner_timezone

    def _owner_day(self, at: datetime) -> date:
        """The owner's calendar day of an instant: "today" for the pantry, not the UTC date."""

        return at.astimezone(self.owner_timezone).date()

    def list_lists(
        self, actor: Actor, *, include_archived: bool = False, limit: int = 50, offset: int = 0
    ) -> ListsResult:
        actor.require("shopping:read")
        self._bounds(limit, offset)

        def read(session: TxSession) -> ListsResult:
            rows = self.store.list_lists(
                session,
                actor.user_id,
                include_archived=include_archived,
                offset=offset,
                limit=limit + 1,
            )
            page, next_offset = paginate(rows, limit, lambda _: offset + limit)
            counts = self.store.open_counts(session, actor.user_id, [row.id for row in page])
            return ListsResult(
                lists=[
                    ListSummary(**list_record(row).model_dump(), open_count=counts.get(row.id, 0))
                    for row in page
                ],
                next_offset=next_offset,
            )

        return self.store.transaction(read)

    def get_list(
        self,
        actor: Actor,
        list_id: UUID,
        *,
        on_date: date | None = None,
        limit: int = 100,
        offset: int = 0,
        store: str | None = None,
    ) -> ListDetail:
        """One list with its items. `store` keeps the items whose store equals it, ignoring case,
        plus the items with no store; a blank store means the whole list."""

        actor.require("shopping:read")
        self._bounds(limit, offset)
        evaluated = on_date or self._owner_day(self.clock.now())
        store_filter = text(store, 200)

        def read(session: TxSession) -> ListDetail:
            row = self.store.get_list(session, actor.user_id, list_id)
            rows = self.store.list_items(
                session,
                actor.user_id,
                list_id,
                store_name=store_filter,
                offset=offset,
                limit=limit + 1,
            )
            page, next_offset = paginate(rows, limit, lambda _: offset + limit)
            names = self._recipient_names(
                session, actor, (item.recipient_contact_id for item in page)
            )
            return ListDetail(
                shopping_list=list_record(row),
                items=[item_record(item, evaluated, names) for item in page],
                next_offset=next_offset,
                evaluated_on=evaluated,
                store=store_filter,
            )

        return self.store.transaction(read)

    def create_list(
        self, actor: Actor, name: str, *, idempotency_key: str, correlation_id: str | None = None
    ) -> ListResult:
        name = required_text(name, 200)

        def execute(session: TxSession) -> ListResult:
            now = self.clock.now()
            row = ShoppingListRow(
                id=new_uuid7(),
                owner_id=actor.user_id,
                name=name,
                archived=False,
                version=1,
                created_at=now,
                updated_at=now,
            )
            session.add(row)
            session.flush()
            self._audit(session, actor, "shopping.list_created", row.id, correlation_id)
            return ListResult(shopping_list=list_record(row))

        return self._write(
            actor,
            "create_list",
            idempotency_key,
            {"name": name},
            execute,
            correlation_id,
            model=ListResult,
            replay=_list_replay,
            rebuild=lambda session, record: self._list_result(session, actor, record),
        )

    def update_list(
        self,
        actor: Actor,
        list_id: UUID,
        *,
        name: str,
        archived: bool,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> ListResult:
        name = required_text(name, 200)

        def execute(session: TxSession) -> ListResult:
            row = self.store.get_list(session, actor.user_id, list_id, lock=True)
            self._version(row.version, version)
            row.name, row.archived = name, archived
            row.version += 1
            row.updated_at = self.clock.now()
            self._audit(session, actor, "shopping.list_updated", row.id, correlation_id)
            return ListResult(shopping_list=list_record(row))

        return self._write(
            actor,
            "update_list",
            idempotency_key,
            {"list_id": str(list_id), "name": name, "archived": archived, "version": version},
            execute,
            correlation_id,
            model=ListResult,
            replay=_list_replay,
            rebuild=lambda session, record: self._list_result(session, actor, record),
        )

    def add_items(
        self,
        actor: Actor,
        list_id: UUID,
        items: list[BatchItem],
        *,
        idempotency_key: str,
        correlation_id: str | None = None,
        merge_duplicates: bool = False,
    ) -> BatchResult:
        """Add 1-50 items. With merge_duplicates, an input whose name and unit (ignoring case)
        match an unpurchased item of the list adds its quantity to that item instead of creating
        a row; the existing item's other fields stay. Inputs of one batch merge with each other."""

        if not 1 <= len(items) <= 50 or len({item.client_ref for item in items}) != len(items):
            raise ValidationError("invalid shopping batch")
        details = [item.domain() for item in items]
        # Scope checks also precede replay: another capability cannot reuse a write key.
        for detail in details:
            if detail.recipient_contact_id is not None:
                actor.require("contacts:read")

        def execute(session: TxSession) -> BatchResult:
            shopping_list = self.store.get_list(session, actor.user_id, list_id, lock=True)
            self._active(shopping_list)
            for detail in details:
                self._validate_details(session, actor, detail)
            now = self.clock.now()
            added: list[AddedItem] = []
            open_rows: dict[tuple[str, str], ShoppingItemRow] = {}
            created: set[UUID] = set()
            if merge_duplicates:
                for existing in self.store.open_items(session, actor.user_id, list_id):
                    open_rows.setdefault(_merge_key(existing.name, existing.unit), existing)
            names = self._recipient_names(
                session,
                actor,
                [
                    *(detail.recipient_contact_id for detail in details),
                    *(existing.recipient_contact_id for existing in open_rows.values()),
                ],
            )
            merged_count = 0
            for position, (source, detail) in enumerate(zip(items, details, strict=True)):
                target = open_rows.get(_merge_key(detail.name, detail.unit))
                if merge_duplicates and target is not None:
                    total = target.quantity + detail.quantity
                    if total <= MAX_QUANTITY:
                        target.quantity = total
                        if target.id not in created:
                            target.version += 1
                            target.updated_at = now
                            self._audit(
                                session, actor, "shopping.item_updated", target.id, correlation_id
                            )
                        merged_count += 1
                        added.append(
                            AddedItem(
                                client_ref=source.client_ref,
                                item=item_record(target, self._owner_day(now), names),
                                merged=True,
                            )
                        )
                        continue
                row = ShoppingItemRow(
                    id=new_uuid7(),
                    owner_id=actor.user_id,
                    list_id=list_id,
                    purchased=False,
                    purchased_at=None,
                    version=1,
                    # Reads order by (created_at, id) and UUIDv7 is random within one
                    # millisecond, so a shared timestamp would shuffle the batch order.
                    created_at=now + timedelta(microseconds=position),
                    updated_at=now,
                )
                self._apply(row, detail)
                session.add(row)
                created.add(row.id)
                if merge_duplicates:
                    open_rows.setdefault(_merge_key(detail.name, detail.unit), row)
                added.append(
                    AddedItem(
                        client_ref=source.client_ref,
                        item=item_record(row, self._owner_day(now), names),
                        merged=False,
                    )
                )
                self._audit(session, actor, "shopping.item_added", row.id, correlation_id)
            return BatchResult(
                items=added,
                evaluated_on=self._owner_day(now),
                list_name=shopping_list.name,
                merged_count=merged_count,
                open_count=self.store.open_count(session, actor.user_id, list_id),
            )

        payload: dict[str, object] = {
            "list_id": str(list_id),
            "items": [item.model_dump(mode="json") for item in items],
        }
        if merge_duplicates:
            # Only sent when set, so a stored key of an earlier plain add still replays unchanged.
            payload["merge_duplicates"] = True

        return self._write(
            actor,
            "add_items",
            idempotency_key,
            payload,
            execute,
            correlation_id,
            model=BatchResult,
            replay=_added_items_replay,
            rebuild=lambda session, record: self._added_items_result(
                session, actor, list_id, items, record
            ),
        )

    def _added_items_result(
        self,
        session: TxSession,
        actor: Actor,
        list_id: UUID,
        items: list[BatchItem],
        record: BatchReplay,
    ) -> BatchResult:
        """The answer of `add_items` rebuilt from its identifier-only record."""

        today = self._owner_day(self.clock.now())
        # The client references come from the retry's own input, which the payload hash ties
        # to the first call.
        rows = [
            self.store.get_item(session, actor.user_id, UUID(entry["item"]["id"]))
            for entry in record["items"]
        ]
        names = self._recipient_names(session, actor, (row.recipient_contact_id for row in rows))
        entries = [
            AddedItem(
                client_ref=source.client_ref,
                item=item_record(row, today, names),
                merged=entry["merged"],
            )
            for source, entry, row in zip(items, record["items"], rows, strict=True)
        ]
        return BatchResult(
            items=entries,
            evaluated_on=today,
            list_name=self.store.get_list(session, actor.user_id, list_id).name,
            merged_count=sum(1 for entry in entries if entry.merged),
            open_count=self.store.open_count(session, actor.user_id, list_id),
        )

    def update_item(
        self,
        actor: Actor,
        item_id: UUID,
        details: ItemDetails | ItemPatch,
        *,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> ItemResult:
        """Full replacement for an ItemDetails; an ItemPatch changes only the fields it holds."""

        patch = details if isinstance(details, ItemPatch) else ItemPatch.full(details)
        if patch.changes().get("recipient_contact_id") is not None:
            actor.require("contacts:read")

        def execute(session: TxSession) -> ItemResult:
            row = self.store.get_item(session, actor.user_id, item_id)
            shopping_list = self.store.get_list(session, actor.user_id, row.list_id, lock=True)
            self._active(shopping_list)
            self._version(row.version, version, row.name)
            merged = merged_details(row, patch)
            self._validate_details(session, actor, merged)
            self._apply(row, merged)
            row.version += 1
            row.updated_at = self.clock.now()
            self._audit(session, actor, "shopping.item_updated", row.id, correlation_id)
            today = self._owner_day(self.clock.now())
            return ItemResult(
                item=self._one_item_record(session, actor, row, today),
                evaluated_on=today,
                list_name=shopping_list.name,
                open_count=self.store.open_count(session, actor.user_id, row.list_id),
            )

        return self._write(
            actor,
            "update_item",
            idempotency_key,
            {"item_id": str(item_id), "version": version, "item": patch.payload()},
            execute,
            correlation_id,
            model=ItemResult,
            replay=_item_replay,
            rebuild=lambda session, record: self._item_result(session, actor, record),
        )

    def set_purchased(
        self,
        actor: Actor,
        item_id: UUID,
        *,
        purchased: bool,
        version: int,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> PurchaseOutcome:
        """Mark one item purchased or wanted. An item already in the asked state is returned
        unchanged (`unchanged` true) even with a stale version; otherwise the version must match."""

        def execute(session: TxSession) -> PurchaseOutcome:
            row = self.store.get_item(session, actor.user_id, item_id)
            shopping_list = self.store.get_list(session, actor.user_id, row.list_id, lock=True)
            self._active(shopping_list)
            now = self.clock.now()
            unchanged = row.purchased == purchased
            if not unchanged:
                self._version(row.version, version, row.name)
                row.purchased, row.purchased_at = purchased, now if purchased else None
                row.version += 1
                row.updated_at = now
                session.add(
                    ShoppingStatusRow(
                        id=new_uuid7(),
                        owner_id=actor.user_id,
                        item_id=row.id,
                        purchased=purchased,
                        item_version=row.version,
                        changed_at=now,
                    )
                )
                self._audit(
                    session,
                    actor,
                    "shopping.item_purchased" if purchased else "shopping.item_reopened",
                    row.id,
                    correlation_id,
                )
            return PurchaseOutcome(
                item=self._one_item_record(session, actor, row, self._owner_day(now)),
                evaluated_on=self._owner_day(now),
                list_name=shopping_list.name,
                open_count=self.store.open_count(session, actor.user_id, row.list_id),
                unchanged=unchanged,
            )

        return self._write(
            actor,
            "set_purchased",
            idempotency_key,
            {"item_id": str(item_id), "version": version, "purchased": purchased},
            execute,
            correlation_id,
            model=PurchaseOutcome,
            replay=_purchase_replay,
            rebuild=lambda session, record: PurchaseOutcome(
                **dict(self._item_result(session, actor, record)), unchanged=record["unchanged"]
            ),
        )

    def set_purchased_many(
        self,
        actor: Actor,
        targets: list[PurchaseTarget],
        *,
        purchased: bool,
        idempotency_key: str,
        correlation_id: str | None = None,
    ) -> PurchasedBatchResult:
        """Mark 1-50 items purchased or wanted in one transaction. Items already in the asked state
        are skipped and listed in `unchanged_item_ids`; for the others every version is checked
        and a stale one fails the whole call."""

        if not 1 <= len(targets) <= 50 or len({t.item_id for t in targets}) != len(targets):
            raise ValidationError("invalid shopping batch")

        def execute(session: TxSession) -> PurchasedBatchResult:
            rows = [self.store.get_item(session, actor.user_id, t.item_id) for t in targets]
            # Lists are locked in id order, so two overlapping batches cannot deadlock.
            for list_id in sorted({row.list_id for row in rows}):
                self._active(self.store.get_list(session, actor.user_id, list_id, lock=True))
            now = self.clock.now()
            # An item already in the asked state is skipped even when its version moved on (bought
            # in the app meanwhile), so one such item no longer stops the rest. Any other stale
            # version still fails the whole call.
            unchanged: list[UUID] = []
            for row, target in zip(rows, targets, strict=True):
                if row.purchased == purchased:
                    unchanged.append(row.id)
                else:
                    self._version(row.version, target.version, row.name)
            for row in rows:
                if row.purchased == purchased:
                    continue
                row.purchased, row.purchased_at = purchased, now if purchased else None
                row.version += 1
                row.updated_at = now
                session.add(
                    ShoppingStatusRow(
                        id=new_uuid7(),
                        owner_id=actor.user_id,
                        item_id=row.id,
                        purchased=purchased,
                        item_version=row.version,
                        changed_at=now,
                    )
                )
                self._audit(
                    session,
                    actor,
                    "shopping.item_purchased" if purchased else "shopping.item_reopened",
                    row.id,
                    correlation_id,
                )
            # open_count only means something for one list; a batch across lists gets None.
            list_ids = {row.list_id for row in rows}
            open_count = (
                self.store.open_count(session, actor.user_id, next(iter(list_ids)))
                if len(list_ids) == 1
                else None
            )
            return PurchasedBatchResult(
                items=self._item_records(session, actor, rows, self._owner_day(now)),
                unchanged_item_ids=unchanged,
                evaluated_on=self._owner_day(now),
                open_count=open_count,
            )

        return self._write(
            actor,
            "set_purchased_many",
            idempotency_key,
            {
                "purchased": purchased,
                "items": [{"item_id": str(t.item_id), "version": t.version} for t in targets],
            },
            execute,
            correlation_id,
            model=PurchasedBatchResult,
            replay=_purchased_batch_replay,
            rebuild=lambda session, record: self._purchased_many_result(session, actor, record),
        )

    def _write[R: BaseModel, Rec](
        self,
        actor: Actor,
        operation: str,
        key: str,
        payload: dict[str, object],
        execute: Callable[[TxSession], R],
        correlation_id: str | None,
        *,
        model: type[R],
        replay: Callable[[R], Rec],
        rebuild: Callable[[TxSession, Rec], R],
    ) -> R:
        """Run one idempotent write; only `replay(result)` is kept and `rebuild` re-reads the rest.

        The idempotency record (`Rec`, a TypedDict of the operation) holds identifiers and flags,
        so a retry returns the records as they are now, never a stored copy of their names or
        notes. The store keeps plain JSON, so the result and the record cross it as such.
        """

        actor.require("shopping:write")
        answer = run_idempotent_operation(
            store=self.store,
            telemetry=self.telemetry,
            logger=LOGGER,
            feature="shopping",
            actor_id=actor.user_id,
            operation=operation,
            key=key,
            payload=payload,
            execute=lambda session: execute(session).model_dump(mode="json"),
            correlation_id=correlation_id,
            replay=lambda result: cast(dict[str, Any], replay(model.model_validate(result))),
            rebuild=lambda session, record: rebuild(session, cast(Rec, record)).model_dump(
                mode="json"
            ),
        )
        return model.model_validate(answer)

    def _list_result(self, session: TxSession, actor: Actor, record: ListReplay) -> ListResult:
        row = self.store.get_list(session, actor.user_id, UUID(record["shopping_list"]["id"]))
        return ListResult(shopping_list=list_record(row))

    def _item_result(self, session: TxSession, actor: Actor, record: ItemReplay) -> ItemResult:
        """One item with its list's name and open count, as a write answers."""

        today = self._owner_day(self.clock.now())
        row = self.store.get_item(session, actor.user_id, UUID(record["item"]["id"]))
        return ItemResult(
            item=self._one_item_record(session, actor, row, today),
            evaluated_on=today,
            list_name=self.store.get_list(session, actor.user_id, row.list_id).name,
            open_count=self.store.open_count(session, actor.user_id, row.list_id),
        )

    def _purchased_many_result(
        self, session: TxSession, actor: Actor, record: PurchasedBatchReplay
    ) -> PurchasedBatchResult:
        today = self._owner_day(self.clock.now())
        rows = [self.store.get_item(session, actor.user_id, UUID(i["id"])) for i in record["items"]]
        list_ids = {row.list_id for row in rows}
        return PurchasedBatchResult(
            items=self._item_records(session, actor, rows, today),
            unchanged_item_ids=[UUID(item_id) for item_id in record["unchanged_item_ids"]],
            evaluated_on=today,
            # open_count only means something for one list; a batch across lists gets None.
            open_count=(
                self.store.open_count(session, actor.user_id, next(iter(list_ids)))
                if len(list_ids) == 1
                else None
            ),
        )

    def _recipient_names(
        self, session: TxSession, actor: Actor, contact_ids: Iterable[UUID | None]
    ) -> dict[UUID, str]:
        """Names of the gift recipients in one query. Empty without the contacts:read scope, so a
        session that cannot read Contacts still sees the recipient link, only without the name."""

        if "contacts:read" not in actor.scopes:
            return {}
        wanted = {contact_id for contact_id in contact_ids if contact_id is not None}
        found = self.store.contact_display_names(session, actor.user_id, tuple(wanted))
        return {contact_id: name for contact_id, (name, _archived) in found.items()}

    def _item_records(
        self, session: TxSession, actor: Actor, rows: list[ShoppingItemRow], on_date: date
    ) -> list[ItemRecord]:
        names = self._recipient_names(session, actor, (row.recipient_contact_id for row in rows))
        return [item_record(row, on_date, names) for row in rows]

    def _one_item_record(
        self, session: TxSession, actor: Actor, row: ShoppingItemRow, on_date: date
    ) -> ItemRecord:
        return self._item_records(session, actor, [row], on_date)[0]

    def _validate_details(self, session: TxSession, actor: Actor, details: ItemDetails) -> None:
        if details.offer is not None and details.offer.checked_on > self._owner_day(
            self.clock.now()
        ):
            raise ValidationError("offer cannot have a future observation date")
        if details.recipient_contact_id is not None:
            actor.require("contacts:read")
            contact = self.store.active_contact(
                session, actor.user_id, details.recipient_contact_id
            )
            if contact is None:
                raise NotFoundError("contact not found")

    def _audit(
        self, session: TxSession, actor: Actor, event: str, target: UUID, correlation_id: str | None
    ) -> None:
        self.store.append_audit(
            session,
            actor_id=actor.user_id,
            event=event,
            outcome="success",
            target_type="shopping",
            target_id=target,
            correlation_id=correlation_id or uuid4().hex,
        )

    @staticmethod
    def _apply(row: ShoppingItemRow, details: ItemDetails) -> None:
        for key in DETAIL_FIELDS:
            setattr(row, key, getattr(details, key))
        for key in OFFER_FIELDS:
            setattr(row, f"offer_{key}", getattr(details.offer, key) if details.offer else None)

    @staticmethod
    def _bounds(limit: int, offset: int) -> None:
        validate_limit(
            limit, maximum=100, message="invalid shopping page bounds", error=ValidationError
        )
        if not 0 <= offset <= 10000:
            raise ValidationError("invalid shopping page bounds")

    @staticmethod
    def _active(row: ShoppingListRow) -> None:
        if row.archived:
            raise ConflictError("shopping list is archived")

    @staticmethod
    def _version(current: int, expected: int, name: str | None = None) -> None:
        if current != expected:
            if name is None:
                raise ConflictError("stale shopping version")
            raise ConflictError(
                "stale shopping version",
                reason="stale_version",
                subject=name,
                subject_kind="shopping_item",
            )
