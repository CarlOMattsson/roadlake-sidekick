import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { maybeConnection, networkFailure } from "@/features/mcp-apps/ui/states";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import {
  CompanionNetworkError,
  CompanionQueuedError,
  CompanionRoomTransport,
} from "@/mobile/companion-transport";
import type { NativeRequest, NativeResponse } from "@/mobile/sidekick-native";
import { fakeNative, nativeError, ok } from "@tests/helpers/fake-native";

// Grupp A (Android UX review): in a shop without coverage a ticked item must not jump back. A purchase that gets no
// answer waits in the phone's outbox ("Waiting for connection"), the list opens from the phone's offline copy with when it
// was fetched, and a failure of the connection says so instead of "Sidekick did not answer".

const LIST_ID = "019f0000-0000-7000-8000-000000000001";
const MILK = "019f0000-0000-7000-8000-0000000000a1";
const BREAD = "019f0000-0000-7000-8000-0000000000a2";
const KEY = "key-0123456789";

const list = {
  id: LIST_ID,
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: MILK,
    list_id: LIST_ID,
    name: "Milk",
    quantity: "1",
    unit: "st",
    note: null,
    occasion: null,
    offer: null,
    offer_status: "none",
    product_url: null,
    purchased: false,
    purchased_at: null,
    recipient_contact_id: null,
    store: null,
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

function detailOf(items: ShoppingItem[]): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-11-11",
    next_offset: null,
    items,
  };
}

/** The room's shopping calls over the companion transport, as room.tsx makes them (the reads and the purchase). */
function shoppingOver(transport: CompanionRoomTransport): ShoppingTransport {
  return {
    offline: transport.offline,
    lists: (offset) =>
      transport.call("list_shopping_lists", {
        include_archived: true,
        limit: 50,
        offset,
      }),
    get: (id, offset) =>
      transport.call("get_shopping_list", {
        list_id: id,
        limit: 100,
        offset,
      }),
    create: () => Promise.reject(new Error("not used")),
    rename: () => Promise.reject(new Error("not used")),
    add: (id, names, key, options) =>
      transport.call("add_shopping_items", {
        list_id: id,
        items: names.map((name, index) => ({
          name,
          client_ref: String(index),
          ...(options?.store ? { store: options.store } : {}),
        })),
        merge_duplicates: options?.mergeDuplicates === true,
        idempotency_key: key,
      }),
    update: () => Promise.reject(new Error("not used")),
    purchase: (row, key) =>
      transport.call("set_shopping_item_purchased", {
        item_id: row.id,
        purchased: !row.purchased,
        version: row.version,
        idempotency_key: key,
      }),
  };
}

describe("the transport offline", () => {
  it("fails with the connection's own error for network and timeout, so the notice names the connection", async () => {
    for (const code of ["network", "timeout"]) {
      const transport = new CompanionRoomTransport(
        fakeNative(() => {
          throw nativeError(code);
        }),
      );
      const failure = await transport
        .call("get_work_agenda", {})
        .catch((error: unknown) => error);
      expect(failure).toBeInstanceOf(CompanionNetworkError);
      expect(failure).not.toBeInstanceOf(HostToolError);
      expect(networkFailure(failure)).toBe(true);
      expect(maybeConnection(failure)).toBe(true);
    }
  });

  it("keeps any other missing answer as the host's own failure", async () => {
    const transport = new CompanionRoomTransport(
      fakeNative(() => {
        throw nativeError("internal");
      }),
    );
    const failure = await transport
      .call("get_work_agenda", {})
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(HostToolError);
    expect(networkFailure(failure)).toBe(false);
  });

  it("puts a purchase without an answer in the outbox with the key and version it was sent with", async () => {
    const native = fakeNative(() => {
      throw nativeError("timeout", 4);
    });
    const transport = new CompanionRoomTransport(native);
    const failure = await transport
      .call("set_shopping_item_purchased", {
        item_id: MILK.toUpperCase(),
        purchased: true,
        version: 3,
        idempotency_key: KEY,
      })
      .catch((error: unknown) => error);
    expect(failure).toBeInstanceOf(CompanionQueuedError);
    expect((failure as CompanionQueuedError).purchased).toBe(true);
    expect(native.queuePurchase).toHaveBeenCalledWith({
      generation: 4, // the pairing the failed request began under, not read again when it is queued
      itemId: MILK,
      version: 3,
      purchased: true,
      idempotencyKey: KEY,
    });
    expect(native.requests[0]?.idempotencyKey).toBe(KEY);
    expect(await transport.offline.queuedPurchases()).toEqual(
      new Map([[MILK, true]]),
    );
  });

  it("queues nothing for a connection failure that does not say which pairing it began under", async () => {
    const native = fakeNative(() => {
      throw nativeError("network");
    });
    const transport = new CompanionRoomTransport(native);
    await expect(
      transport.call("set_shopping_item_purchased", {
        item_id: MILK,
        purchased: true,
        version: 3,
        idempotency_key: KEY,
      }),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
    expect(native.queuePurchase).not.toHaveBeenCalled();
  });

  it("queues nothing for an answer the server gave, nor for a failure that is not the connection", async () => {
    let answer: () => NativeResponse = () => ({
      status: 503,
      body: { code: "unavailable" },
    });
    const native = fakeNative(() => answer());
    const transport = new CompanionRoomTransport(native);
    const args = {
      item_id: MILK,
      purchased: true,
      version: 3,
      idempotency_key: KEY,
    };
    await expect(
      transport.call("set_shopping_item_purchased", args),
    ).rejects.toBeInstanceOf(HostToolError);
    answer = () => {
      throw nativeError("not_paired");
    };
    await expect(
      transport.call("set_shopping_item_purchased", args),
    ).rejects.toBeInstanceOf(HostToolError);
    expect(native.queuePurchase).not.toHaveBeenCalled();
  });

  it("tells which answer came from the offline copy, and when that copy was read", async () => {
    const at = Date.UTC(2026, 10, 11, 13, 2);
    const native = fakeNative((request: NativeRequest) =>
      request.path.endsWith(LIST_ID)
        ? { status: 200, body: detailOf([]), cachedAt: at }
        : ok({ lists: [list], next_offset: null }),
    );
    const transport = new CompanionRoomTransport(native);
    const copy = await transport.call<object>("get_shopping_list", {
      list_id: LIST_ID,
    });
    const fresh = await transport.call<object>("list_shopping_lists", {});
    expect(transport.offline.readAt(copy)).toBe(at);
    expect(transport.offline.readAt(fresh)).toBeUndefined();
  });
});

describe("items added without coverage", () => {
  const ADD_KEY = "add-key-0123456789";
  const addArgs = (over: object = {}) => ({
    list_id: LIST_ID.toUpperCase(),
    items: [{ name: "Bread", client_ref: "0", store: "ICA" }],
    merge_duplicates: true,
    idempotency_key: ADD_KEY,
    ...over,
  });
  const offlineNative = (generation: number | null = 4) =>
    fakeNative((request: NativeRequest) => {
      if (request.method === "POST")
        throw nativeError("timeout", generation ?? undefined);
      return ok(detailOf([item({})]));
    });

  it("queues an add without an answer with the key and body it was sent with, and answers with stand-in rows", async () => {
    const native = offlineNative();
    const transport = new CompanionRoomTransport(native);
    const result = await transport.call<{
      items: { item: ShoppingItem; merged: boolean }[];
    }>("add_shopping_items", addArgs());
    expect(native.queueShoppingAdd).toHaveBeenCalledWith({
      generation: 4,
      listId: LIST_ID,
      idempotencyKey: ADD_KEY,
      body: {
        items: [{ name: "Bread", client_ref: "0", store: "ICA" }],
        merge_duplicates: true,
      },
    });
    expect(native.requests[0]?.idempotencyKey).toBe(ADD_KEY);
    const [added] = result.items;
    expect(added?.merged).toBe(false);
    expect(added?.item).toMatchObject({
      name: "Bread",
      store: "ICA",
      purchased: false,
      list_id: LIST_ID,
    });
    // Waiting, not bought: the room draws the stand-in as waiting and takes no tap on it.
    expect(await transport.offline.queuedPurchases()).toEqual(
      new Map([[added!.item.id, false]]),
    );
  });

  it("tells the room's listeners before it answers, so the list already knows which rows wait", async () => {
    const transport = new CompanionRoomTransport(offlineNative());
    let told = 0;
    const stop = transport.offline.onQueueChanged(() => told++);
    await transport.call("add_shopping_items", addArgs());
    expect(told).toBe(1);
    stop();
    await transport.call(
      "add_shopping_items",
      addArgs({ idempotency_key: "add-key-other-0002" }),
    );
    expect(told).toBe(1);
  });

  it("queues the same add once when the page repeats the call with the same key", async () => {
    const native = offlineNative();
    const transport = new CompanionRoomTransport(native);
    await transport.call("add_shopping_items", addArgs());
    await transport.call("add_shopping_items", addArgs());
    expect(native.addOutbox.size).toBe(1);
    expect(native.requests.map((r) => r.idempotencyKey)).toEqual([
      ADD_KEY,
      ADD_KEY,
    ]);
  });

  it("generates one key per add when the room gives none and reuses it for the retry", async () => {
    const native = offlineNative();
    const transport = new CompanionRoomTransport(native);
    const args = addArgs();
    delete (args as { idempotency_key?: string }).idempotency_key;
    await transport.call("add_shopping_items", args);
    // Queued: the outbox owns the key now, a later add of the same text is a new add.
    await transport.call("add_shopping_items", args);
    const keys = native.requests.map((r) => r.idempotencyKey);
    expect(keys[0]).toBeTruthy();
    expect(keys[1]).not.toBe(keys[0]);
  });

  it("queues nothing without the pairing generation, nor for an answer the server gave", async () => {
    const withoutGeneration = offlineNative(null);
    await expect(
      new CompanionRoomTransport(withoutGeneration).call(
        "add_shopping_items",
        addArgs(),
      ),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
    expect(withoutGeneration.queueShoppingAdd).not.toHaveBeenCalled();

    const refused = fakeNative(() => ({
      status: 422,
      body: { code: "validation_error" },
    }));
    await expect(
      new CompanionRoomTransport(refused).call("add_shopping_items", addArgs()),
    ).rejects.toBeInstanceOf(HostToolError);
    expect(refused.queueShoppingAdd).not.toHaveBeenCalled();
  });

  it("fails with the connection error when the phone could not keep the add", async () => {
    const native = offlineNative();
    native.queueShoppingAdd.mockResolvedValue({ queued: false });
    await expect(
      new CompanionRoomTransport(native).call("add_shopping_items", addArgs()),
    ).rejects.toBeInstanceOf(CompanionNetworkError);
  });

  it("appends the waiting items to the list's last page, in the shop asked for, and keeps the copy's time", async () => {
    const at = Date.UTC(2026, 10, 11, 13, 2);
    const native = fakeNative((request: NativeRequest) => {
      if (request.method === "POST") throw nativeError("network", 1);
      return { status: 200, body: detailOf([item({})]), cachedAt: at };
    });
    const transport = new CompanionRoomTransport(native);
    await transport.call("add_shopping_items", addArgs());
    await transport.call(
      "add_shopping_items",
      addArgs({
        items: [{ name: "Rice", client_ref: "0", store: "Coop" }],
        idempotency_key: "add-key-other-0002",
      }),
    );
    await transport.call(
      "add_shopping_items",
      addArgs({
        items: [{ name: "Salt", client_ref: "0" }],
        idempotency_key: "add-key-other-0003",
      }),
    );
    const names = async (args: object) => {
      const page = await transport.call<ShoppingDetail>("get_shopping_list", {
        list_id: LIST_ID,
        ...args,
      });
      return { page, names: page.items.map((row) => row.name) };
    };
    const all = await names({});
    expect(all.names).toEqual(["Milk", "Bread", "Rice", "Salt"]);
    expect(transport.offline.readAt(all.page)).toBe(at);
    expect((await names({ store: "ica" })).names).toEqual([
      "Milk",
      "Bread",
      "Salt",
    ]);
    // Another list's read is left alone.
    const other = await transport.call<ShoppingDetail>("get_shopping_list", {
      list_id: MILK,
    });
    expect(other.items.map((row) => row.name)).toEqual(["Milk"]);
  });

  it("leaves a page that has more after it as the server sent it", async () => {
    const native = fakeNative((request: NativeRequest) => {
      if (request.method === "POST") throw nativeError("network", 1);
      return ok({ ...detailOf([item({})]), next_offset: 100 });
    });
    const transport = new CompanionRoomTransport(native);
    await transport.call("add_shopping_items", addArgs());
    const page = await transport.call<ShoppingDetail>("get_shopping_list", {
      list_id: LIST_ID,
    });
    expect(page.items.map((row) => row.name)).toEqual(["Milk"]);
  });
});

describe("the Shopping room in a shop without coverage", () => {
  function phone(options: { online: boolean; cachedAt?: number }) {
    const state = { online: options.online };
    const native = fakeNative((request: NativeRequest) => {
      if (request.method === "POST") {
        if (!state.online) throw nativeError("network", 0);
        const body = request.body as { purchased: boolean; version: number };
        return ok({
          item: item({ purchased: body.purchased, version: body.version + 1 }),
        });
      }
      if (request.path.endsWith(LIST_ID)) {
        const items = [item({}), item({ id: BREAD, name: "Bread" })];
        return {
          status: 200,
          body: detailOf(items),
          ...(options.cachedAt ? { cachedAt: options.cachedAt } : {}),
        };
      }
      return ok({ lists: [list], next_offset: null });
    });
    const transport = new CompanionRoomTransport(native);
    render(
      <ShoppingView
        transport={shoppingOver(transport)}
        labels={shoppingEn}
        listId={LIST_ID}
        fullscreen
      />,
    );
    return { native, state };
  }

  it("keeps a ticked item bought and waiting for the network instead of taking it back", async () => {
    const user = userEvent.setup();
    const { native } = phone({ online: false });
    const milk = await screen.findByRole("button", {
      name: "Mark Milk as bought",
    });
    await user.click(milk);
    await waitFor(() => expect(native.queuePurchase).toHaveBeenCalledTimes(1));
    expect(
      screen.getByRole("button", { name: "Mark Milk as not bought" }),
    ).toBeDisabled();
    expect(
      screen.getAllByText(shoppingEn.waitingForNetwork).length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("alert")).toBeNull();
    // Every row can wait at once: there is no single "last failed write".
    await user.click(
      screen.getByRole("button", { name: "Mark Bread as bought" }),
    );
    await waitFor(() => expect(native.outbox.size).toBe(2));
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("reads the list again once the outbox has sent the purchase", async () => {
    const user = userEvent.setup();
    const { native, state } = phone({ online: false });
    await user.click(
      await screen.findByRole("button", { name: "Mark Milk as bought" }),
    );
    await waitFor(() => expect(native.outbox.size).toBe(1));
    const readsBefore = native.requests.filter((r) =>
      r.path.endsWith(LIST_ID),
    ).length;
    state.online = true;
    act(() => native.runOutbox());
    await waitFor(() =>
      expect(
        native.requests.filter((r) => r.path.endsWith(LIST_ID)).length,
      ).toBeGreaterThan(readsBefore),
    );
    await waitFor(() =>
      expect(screen.queryByText(shoppingEn.waitingForNetwork)).toBeNull(),
    );
  });

  it("does not leave a row waiting when the outbox ran before the queueing was acknowledged", async () => {
    const user = userEvent.setup();
    const { native } = phone({ online: false });
    // The phone queues the purchase, the sync sends it and fires queueChanged, and only then is the queueing answered.
    native.queuePurchase.mockImplementation(async (options) => {
      native.outbox.set(options.itemId, options);
      native.runOutbox();
      await new Promise((resolve) => setTimeout(resolve, 0));
      return { queued: true, purchased: options.purchased };
    });
    const milk = await screen.findByRole("button", {
      name: "Mark Milk as bought",
    });
    const readsBefore = native.requests.filter((r) =>
      r.path.endsWith(LIST_ID),
    ).length;
    await user.click(milk);
    await waitFor(() => expect(native.queuePurchase).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.queryByText(shoppingEn.waitingForNetwork)).toBeNull(),
    );
    expect(native.outbox.size).toBe(0);
    expect(
      native.requests.filter((r) => r.path.endsWith(LIST_ID)).length,
    ).toBeGreaterThan(readsBefore);
  });

  it("shows an item added without coverage as waiting, and the real row once the outbox has sent it", async () => {
    const user = userEvent.setup();
    const state = { online: false, added: false };
    const native = fakeNative((request: NativeRequest) => {
      if (request.method === "POST") {
        if (!state.online) throw nativeError("network", 0);
        state.added = true;
        return ok({
          items: [{ item: item({ id: BREAD, name: "Bread" }), merged: false }],
        });
      }
      if (request.path.endsWith(LIST_ID))
        return ok(
          detailOf(
            state.added
              ? [item({}), item({ id: BREAD, name: "Bread" })]
              : [item({})],
          ),
        );
      return ok({ lists: [list], next_offset: null });
    });
    render(
      <ShoppingView
        transport={shoppingOver(new CompanionRoomTransport(native))}
        labels={shoppingEn}
        listId={LIST_ID}
        fullscreen
      />,
    );
    await screen.findByRole("button", { name: "Mark Milk as bought" });
    await user.click(screen.getByRole("button", { name: shoppingEn.addItem }));
    const field = screen.getByRole("textbox", { name: shoppingEn.addItem });
    await user.type(field, "Bread");
    await user.click(
      screen.getByRole("button", { name: shoppingEn.addItemButton }),
    );
    await waitFor(() =>
      expect(native.queueShoppingAdd).toHaveBeenCalledTimes(1),
    );
    // The row is there, waiting and untouchable, announced to a screen reader, and no failure is shown.
    const waiting = await screen.findByRole("button", {
      name: "Mark Bread as bought",
    });
    await waitFor(() => expect(waiting).toBeDisabled());
    // Its change form cannot be opened either, and the receipt says it is sent once the network is back.
    const row = waiting
      .closest("li")
      ?.querySelector<HTMLButtonElement>(".shopping-store-row");
    expect(row).toBeDisabled();
    expect(
      await screen.findByText(shoppingEn.addQueued("Bread")),
    ).toBeInTheDocument();
    expect(screen.queryByRole("alert")).toBeNull();
    expect(
      screen.getAllByText(shoppingEn.waitingForNetwork).length,
    ).toBeGreaterThan(0);
    expect(field).toHaveValue("");

    // Back in coverage: the phone sends the add under its key; the list is read again and shows the real row.
    state.online = true;
    state.added = true;
    act(() => native.runOutbox());
    await waitFor(() =>
      expect(screen.queryByText(shoppingEn.waitingForNetwork)).toBeNull(),
    );
    expect(
      await screen.findByRole("button", { name: "Mark Bread as bought" }),
    ).toBeEnabled();
    expect(native.addOutbox.size).toBe(0);
  });

  it("opens the offline copy with when it was fetched", async () => {
    const at = new Date();
    at.setHours(14, 2, 0, 0);
    phone({ online: false, cachedAt: at.getTime() });
    expect(
      await screen.findByText(
        /^No connection · last fetched .*\d{2}[:.]\d{2}$/,
      ),
    ).toBeInTheDocument();
  });

  it("says nothing about a copy when the server answered", async () => {
    phone({ online: true });
    await screen.findByRole("button", { name: "Mark Milk as bought" });
    expect(screen.queryByText(/last fetched/)).toBeNull();
  });
});

describe("the offline texts", () => {
  it("are written in Swedish first and in English", () => {
    expect(shoppingSv.waitingForNetwork).toBe("Väntar på anslutning");
    expect(shoppingSv.offlineCopy("14:02")).toBe(
      "Ingen anslutning · senast hämtad 14:02",
    );
    expect(shoppingEn.waitingForNetwork).toBe("Waiting for connection");
    expect(shoppingEn.offlineCopy("14:02")).toBe(
      "No connection · last fetched 14:02",
    );
  });
});
