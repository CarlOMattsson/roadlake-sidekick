"""Shopping application use cases shared by HTTP, MCP and the interactive app."""

import logging
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, replace
from datetime import date, datetime, timedelta, tzinfo
from decimal import Decimal
from typing import TypedDict
from uuid import UUID, uuid4

from pydantic import BaseModel

from sidekick.shared.config import DEFAULT_OWNER_TIMEZONE, parse_owner_timezone
from sidekick.shared.errors import ConflictError, NotFoundError, ValidationError
from sidekick.shared.idempotent_operation import run_idempotent_model_operation
from sidekick.shared.observability import TelemetryPort
from sidekick.shared.replay import IdRecord
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
from sidekick.shopping.application.store import ShoppingStore
from sidekick.shopping.domain import (
    DETAIL_FIELDS,
    ItemDetails,
    Offer,
    PurchaseChange,
    ShoppingItem,
    ShoppingList,
    required_text,
    text,
)

LOGGER = logging.getLogger("sidekick.shopping")
ITEM_FIELDS = (*DETAIL_FIELDS, "offer")

DEFAULT_OWNER_ZONE = parse_owner_timezone(DEFAULT_OWNER_TIMEZONE)


MAX_QUANTITY = Decimal("999999.999")


def _merge_key(name: str, unit: str | None) -> tuple[str, str]:
    """Name and unit as compared by merge_duplicates: case-insensitive, no unit equals no unit."""

    return (name.casefold(), (unit or "").casefold())


class ListReplay(TypedDict):
    shopping_list: IdRecord


class ItemReplay(TypedDict):
    item: IdRecord


class PurchaseReplay(ItemReplay):
    unchanged: bool


class AddedItemReplay(TypedDict):
    item: IdRecord
    merged: bool


class BatchReplay(TypedDict):
    items: list[AddedItemReplay]


class PurchasedBatchReplay(TypedDict):
    items: list[IdRecord]
    unchanged_item_ids: list[str]


def _ref(record_id: UUID) -> IdRecord:
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


def merged_details(item: ShoppingItem, patch: ItemPatch) -> ItemDetails:
    """The stored item's details with only the patched fields replaced."""

    return replace(item.details, **patch.changes())


def _with_added_quantity(
    held: ShoppingItem, quantity: Decimal, now: datetime, *, bump: bool
) -> ShoppingItem | None:
    """The item with `quantity` added, or None when the total would pass the largest quantity.
    `bump` also moves its version and update time on, as every stored change does."""

    total = held.details.quantity + quantity
    if total > MAX_QUANTITY:
        return None
    merged = replace(held, details=replace(held.details, quantity=total))
    return replace(merged, version=held.version + 1, updated_at=now) if bump else merged


def _new_item(
    actor: Actor, list_id: UUID, details: ItemDetails, now: datetime, position: int
) -> ShoppingItem:
    return ShoppingItem(
        id=new_uuid7(),
        owner_id=actor.user_id,
        list_id=list_id,
        details=details,
        purchased=False,
        purchased_at=None,
        version=1,
        # Reads order by (created_at, id) and UUIDv7 is random within one millisecond, so a
        # shared timestamp would shuffle the batch order.
        created_at=now + timedelta(microseconds=position),
        updated_at=now,
    )


def list_record(shopping_list: ShoppingList) -> ListRecord:
    return ListRecord.model_validate(shopping_list, from_attributes=True)


def item_record(item: ShoppingItem, on_date: date, names: Mapping[UUID, str]) -> ItemRecord:
    details = item.details
    offer = None if details.offer is None else OfferInput.model_validate(asdict(details.offer))
    recipient = details.recipient_contact_id
    return ItemRecord(
        **{key: getattr(details, key) for key in DETAIL_FIELDS},
        id=item.id,
        list_id=item.list_id,
        purchased=item.purchased,
        purchased_at=item.purchased_at,
        version=item.version,
        created_at=item.created_at,
        updated_at=item.updated_at,
        offer=offer,
        offer_status="none" if details.offer is None else details.offer.status(on_date),
        recipient_contact_name=names.get(recipient) if recipient is not None else None,
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
            lists = self.store.list_lists(
                session,
                actor.user_id,
                include_archived=include_archived,
                offset=offset,
                limit=limit + 1,
            )
            page, next_offset = paginate(lists, limit, lambda _: offset + limit)
            counts = self.store.open_counts(session, actor.user_id, [entry.id for entry in page])
            return ListsResult(
                lists=[
                    ListSummary(
                        **list_record(entry).model_dump(), open_count=counts.get(entry.id, 0)
                    )
                    for entry in page
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
            shopping_list = self.store.get_list(session, actor.user_id, list_id)
            found = self.store.list_items(
                session,
                actor.user_id,
                list_id,
                store_name=store_filter,
                offset=offset,
                limit=limit + 1,
            )
            page, next_offset = paginate(found, limit, lambda _: offset + limit)
            names = self._recipient_names(
                session, actor, (item.details.recipient_contact_id for item in page)
            )
            return ListDetail(
                shopping_list=list_record(shopping_list),
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
            created = ShoppingList(
                id=new_uuid7(),
                owner_id=actor.user_id,
                name=name,
                archived=False,
                version=1,
                created_at=now,
                updated_at=now,
            )
            self.store.add_list(session, created)
            self._audit(session, actor, "shopping.list_created", created.id, correlation_id)
            return ListResult(shopping_list=list_record(created))

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
            current = self.store.get_list(session, actor.user_id, list_id, lock=True)
            self._version(current.version, version)
            updated = replace(
                current,
                name=name,
                archived=archived,
                version=current.version + 1,
                updated_at=self.clock.now(),
            )
            self.store.save_list(session, updated)
            self._audit(session, actor, "shopping.list_updated", updated.id, correlation_id)
            return ListResult(shopping_list=list_record(updated))

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
            open_items: dict[tuple[str, str], ShoppingItem] = {}
            created: dict[UUID, ShoppingItem] = {}
            merged_into: dict[UUID, ShoppingItem] = {}
            if merge_duplicates:
                for existing in self.store.open_items(session, actor.user_id, list_id):
                    key = _merge_key(existing.details.name, existing.details.unit)
                    open_items.setdefault(key, existing)
            names = self._recipient_names(
                session,
                actor,
                [
                    *(detail.recipient_contact_id for detail in details),
                    *(existing.details.recipient_contact_id for existing in open_items.values()),
                ],
            )
            merged_count = 0
            for position, (source, detail) in enumerate(zip(items, details, strict=True)):
                key = _merge_key(detail.name, detail.unit)
                target = open_items.get(key)
                if merge_duplicates and target is not None:
                    is_new = target.id in created
                    merged = _with_added_quantity(target, detail.quantity, now, bump=not is_new)
                    if merged is not None:
                        open_items[key] = merged
                        (created if is_new else merged_into)[merged.id] = merged
                        if not is_new:
                            self._audit(
                                session, actor, "shopping.item_updated", merged.id, correlation_id
                            )
                        merged_count += 1
                        added.append(
                            AddedItem(
                                client_ref=source.client_ref,
                                item=item_record(merged, self._owner_day(now), names),
                                merged=True,
                            )
                        )
                        continue
                new_item = _new_item(actor, list_id, detail, now, position)
                created[new_item.id] = new_item
                if merge_duplicates:
                    open_items.setdefault(key, new_item)
                added.append(
                    AddedItem(
                        client_ref=source.client_ref,
                        item=item_record(new_item, self._owner_day(now), names),
                        merged=False,
                    )
                )
                self._audit(session, actor, "shopping.item_added", new_item.id, correlation_id)
            for item in merged_into.values():
                self.store.save_item(session, item)
            for item in created.values():
                self.store.add_item(session, item)
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
        stored = [
            self.store.get_item(session, actor.user_id, UUID(entry["item"]["id"]))
            for entry in record["items"]
        ]
        names = self._recipient_names(
            session, actor, (item.details.recipient_contact_id for item in stored)
        )
        entries = [
            AddedItem(
                client_ref=source.client_ref,
                item=item_record(item, today, names),
                merged=entry["merged"],
            )
            for source, entry, item in zip(items, record["items"], stored, strict=True)
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
            current = self.store.get_item(session, actor.user_id, item_id)
            shopping_list = self.store.get_list(session, actor.user_id, current.list_id, lock=True)
            self._active(shopping_list)
            self._version(current.version, version, current.details.name)
            merged = merged_details(current, patch)
            self._validate_details(session, actor, merged)
            updated = replace(
                current,
                details=merged,
                version=current.version + 1,
                updated_at=self.clock.now(),
            )
            self.store.save_item(session, updated)
            self._audit(session, actor, "shopping.item_updated", updated.id, correlation_id)
            today = self._owner_day(self.clock.now())
            return ItemResult(
                item=self._one_item_record(session, actor, updated, today),
                evaluated_on=today,
                list_name=shopping_list.name,
                open_count=self.store.open_count(session, actor.user_id, updated.list_id),
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
            current = self.store.get_item(session, actor.user_id, item_id)
            shopping_list = self.store.get_list(session, actor.user_id, current.list_id, lock=True)
            self._active(shopping_list)
            now = self.clock.now()
            unchanged = current.purchased == purchased
            item = current
            if not unchanged:
                self._version(current.version, version, current.details.name)
                item = self._set_purchased(session, actor, current, purchased, now, correlation_id)
            return PurchaseOutcome(
                item=self._one_item_record(session, actor, item, self._owner_day(now)),
                evaluated_on=self._owner_day(now),
                list_name=shopping_list.name,
                open_count=self.store.open_count(session, actor.user_id, item.list_id),
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
            stored = [self.store.get_item(session, actor.user_id, t.item_id) for t in targets]
            # Lists are locked in id order, so two overlapping batches cannot deadlock.
            for list_id in sorted({item.list_id for item in stored}):
                self._active(self.store.get_list(session, actor.user_id, list_id, lock=True))
            now = self.clock.now()
            # An item already in the asked state is skipped even when its version moved on (bought
            # in the app meanwhile), so one such item no longer stops the rest. Any other stale
            # version still fails the whole call.
            unchanged: list[UUID] = []
            for item, target in zip(stored, targets, strict=True):
                if item.purchased == purchased:
                    unchanged.append(item.id)
                else:
                    self._version(item.version, target.version, item.details.name)
            items = [
                item
                if item.purchased == purchased
                else self._set_purchased(session, actor, item, purchased, now, correlation_id)
                for item in stored
            ]
            # open_count only means something for one list; a batch across lists gets None.
            list_ids = {item.list_id for item in stored}
            open_count = (
                self.store.open_count(session, actor.user_id, next(iter(list_ids)))
                if len(list_ids) == 1
                else None
            )
            return PurchasedBatchResult(
                items=self._item_records(session, actor, items, self._owner_day(now)),
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
        return run_idempotent_model_operation(
            store=self.store,
            telemetry=self.telemetry,
            logger=LOGGER,
            feature="shopping",
            actor_id=actor.user_id,
            operation=operation,
            key=key,
            payload=payload,
            execute=execute,
            correlation_id=correlation_id,
            model=model,
            replay=replay,
            rebuild=rebuild,
        )

    def _list_result(self, session: TxSession, actor: Actor, record: ListReplay) -> ListResult:
        stored = self.store.get_list(session, actor.user_id, UUID(record["shopping_list"]["id"]))
        return ListResult(shopping_list=list_record(stored))

    def _item_result(self, session: TxSession, actor: Actor, record: ItemReplay) -> ItemResult:
        """One item with its list's name and open count, as a write answers."""

        today = self._owner_day(self.clock.now())
        item = self.store.get_item(session, actor.user_id, UUID(record["item"]["id"]))
        return ItemResult(
            item=self._one_item_record(session, actor, item, today),
            evaluated_on=today,
            list_name=self.store.get_list(session, actor.user_id, item.list_id).name,
            open_count=self.store.open_count(session, actor.user_id, item.list_id),
        )

    def _purchased_many_result(
        self, session: TxSession, actor: Actor, record: PurchasedBatchReplay
    ) -> PurchasedBatchResult:
        today = self._owner_day(self.clock.now())
        stored = [
            self.store.get_item(session, actor.user_id, UUID(i["id"])) for i in record["items"]
        ]
        list_ids = {item.list_id for item in stored}
        return PurchasedBatchResult(
            items=self._item_records(session, actor, stored, today),
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
        self, session: TxSession, actor: Actor, items: list[ShoppingItem], on_date: date
    ) -> list[ItemRecord]:
        names = self._recipient_names(
            session, actor, (item.details.recipient_contact_id for item in items)
        )
        return [item_record(item, on_date, names) for item in items]

    def _one_item_record(
        self, session: TxSession, actor: Actor, item: ShoppingItem, on_date: date
    ) -> ItemRecord:
        return self._item_records(session, actor, [item], on_date)[0]

    def _set_purchased(
        self,
        session: TxSession,
        actor: Actor,
        item: ShoppingItem,
        purchased: bool,
        now: datetime,
        correlation_id: str | None,
    ) -> ShoppingItem:
        """Move one item to the asked state: save it, add its history row and audit the change."""

        changed = replace(
            item,
            purchased=purchased,
            purchased_at=now if purchased else None,
            version=item.version + 1,
            updated_at=now,
        )
        self.store.save_item(session, changed)
        self.store.add_purchase_change(
            session,
            PurchaseChange(
                id=new_uuid7(),
                owner_id=actor.user_id,
                item_id=item.id,
                purchased=purchased,
                item_version=changed.version,
                changed_at=now,
            ),
        )
        self._audit(
            session,
            actor,
            "shopping.item_purchased" if purchased else "shopping.item_reopened",
            item.id,
            correlation_id,
        )
        return changed

    def _validate_details(self, session: TxSession, actor: Actor, details: ItemDetails) -> None:
        if details.offer is not None and details.offer.checked_on > self._owner_day(
            self.clock.now()
        ):
            raise ValidationError("offer cannot have a future observation date")
        if details.recipient_contact_id is not None:
            actor.require("contacts:read")
            if not self.store.has_active_contact(
                session, actor.user_id, details.recipient_contact_id
            ):
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
    def _bounds(limit: int, offset: int) -> None:
        validate_limit(
            limit, maximum=100, message="invalid shopping page bounds", error=ValidationError
        )
        if not 0 <= offset <= 10000:
            raise ValidationError("invalid shopping page bounds")

    @staticmethod
    def _active(shopping_list: ShoppingList) -> None:
        if shopping_list.archived:
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
