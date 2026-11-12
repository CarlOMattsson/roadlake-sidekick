import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// Performance: a purchase is a write of its own row. The row shows it at once, a tap while the row's write runs
// waits ("Waiting…"), other rows are free, and the reply replaces the row: no read of the list.

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const milkId = "019f0000-0000-7000-8000-0000000000a1";
const breadId = "019f0000-0000-7000-8000-0000000000a2";

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: milkId,
    list_id: list.id,
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

const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [
    item({ id: milkId, name: "Milk" }),
    item({ id: breadId, name: "Bread" }),
  ],
};

type Deferred = { resolve: (value: { item: ShoppingItem }) => void };

function adapter() {
  const pending: Deferred[] = [];
  const purchase = vi.fn(
    (row: ShoppingItem) =>
      new Promise<{ item: ShoppingItem }>((resolve) => {
        pending.push({
          resolve: () =>
            resolve({
              item: {
                ...row,
                purchased: !row.purchased,
                version: row.version + 1,
              },
            }),
        });
      }),
  );
  const transport: ShoppingTransport = {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase,
  };
  return { transport, purchase, pending };
}

function open(transport: ShoppingTransport) {
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
}

it("opens from the result it was given: no read of the list, one of the register", async () => {
  const { transport } = adapter();
  open(transport);
  expect(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  ).toBeEnabled();
  expect(transport.get).not.toHaveBeenCalled();
  expect(transport.lists).toHaveBeenCalledTimes(1);
});

it("shows a purchase at once, writes once and reads nothing after the reply", async () => {
  const user = userEvent.setup();
  const { transport, purchase, pending } = adapter();
  open(transport);
  const milk = await screen.findByRole("button", { name: /^Mark Milk as/ });
  await user.click(milk);
  expect(milk).toHaveAccessibleName(/as not bought/);
  // The other row stays free while this one is saving.
  expect(screen.getByRole("button", { name: /^Mark Bread as/ })).toBeEnabled();
  act(() => pending[0]!.resolve({ item: item({}) }));
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Undo/ })).toBeInTheDocument(),
  );
  expect(purchase).toHaveBeenCalledTimes(1);
  expect(transport.get).not.toHaveBeenCalled();
  expect(transport.lists).toHaveBeenCalledTimes(1);
});

it("queues a second tap on the same row, shows it waits, and sends it with the version of the first reply", async () => {
  const user = userEvent.setup();
  const { transport, purchase, pending } = adapter();
  open(transport);
  const milk = await screen.findByRole("button", { name: /^Mark Milk as/ });
  await user.click(milk);
  const bread = screen.getByRole("button", { name: /^Mark Bread as/ });
  await user.click(milk);
  // The row's mark is drawn for the eye; the announcement is one stable status region outside the busy row.
  expect(screen.getAllByText(shoppingEn.queued).length).toBeGreaterThan(0);
  expect(purchase).toHaveBeenCalledTimes(1);
  // Another row is not held by the waiting one.
  await user.click(bread);
  expect(purchase).toHaveBeenCalledTimes(2);
  act(() => pending[0]!.resolve({ item: item({}) }));
  await waitFor(() => expect(purchase).toHaveBeenCalledTimes(3));
  const second = purchase.mock.calls.find(
    ([row], index) => index === 2 && row.id === milkId,
  );
  expect(second![0].version).toBe(2);
  expect(second![0].purchased).toBe(true);
  act(() => pending[2]!.resolve({ item: item({}) }));
  await waitFor(() =>
    expect(screen.queryAllByText(shoppingEn.queued)).toHaveLength(0),
  );
  expect(milk).toHaveAccessibleName(/as bought/);
});

it("puts the row back and shows a failure line in it when the write fails", async () => {
  const user = userEvent.setup();
  const { transport, purchase } = adapter();
  purchase.mockRejectedValueOnce(new Error("network down"));
  open(transport);
  const milk = await screen.findByRole("button", { name: /^Mark Milk as/ });
  await user.click(milk);
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: shoppingEn.retry }),
    ).toBeVisible(),
  );
  expect(milk).toHaveAccessibleName(/as bought/);
});

it("a newer result for the same list replaces the list the room shows", async () => {
  const { ShoppingRoom } = await import("@/features/shopping-app/room");
  const call = vi.fn(() => new Promise(() => undefined));
  const transport = {
    call: call as never,
    requestDisplayMode: vi.fn() as never,
    updateModelContext: vi.fn() as never,
  };
  const newer: ShoppingDetail = {
    ...detail,
    items: [...detail.items, item({ id: "x", name: "Cheese" })],
  };
  const { rerender } = render(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={detail}
      resultId={1}
    />,
  );
  expect(await screen.findByText("Milk")).toBeInTheDocument();
  rerender(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={newer}
      resultId={2}
    />,
  );
  expect(await screen.findByText("Cheese")).toBeInTheDocument();
  expect(call).not.toHaveBeenCalledWith("get_shopping_list", expect.anything());
});

it("announces the wait in a status region outside the aria-busy row", async () => {
  const user = userEvent.setup();
  const { transport } = adapter();
  open(transport);
  const milk = await screen.findByRole("button", { name: /^Mark Milk as/ });
  await user.click(milk);
  await user.click(milk);
  const region = screen
    .getAllByText(shoppingEn.queued)
    .find((node) => node.getAttribute("aria-live") === "polite");
  expect(region).toBeDefined();
  expect(region!.closest("[aria-busy]")).toBeNull();
  expect(milk.closest("li")).toHaveAttribute("aria-busy", "true");
});

it("settles an unanswered purchase with its own key before a queued Undo is judged", async () => {
  const user = userEvent.setup();
  const { transport, purchase } = adapter();
  // The server bought the milk (v2) but the answer never came; the same key replays the stored result.
  let serverItem = item({});
  const keys: string[] = [];
  let lost = true;
  let timeout = () => {};
  purchase.mockReset();
  purchase.mockImplementation((row: ShoppingItem, key?: string) => {
    keys.push(key ?? "");
    if (key === keys[0] && !lost) return Promise.resolve({ item: serverItem });
    if (key === keys[0]) {
      serverItem = { ...row, purchased: true, version: row.version + 1 };
      lost = false;
      return new Promise((_, reject) => {
        timeout = () => reject(new Error("timeout"));
      });
    }
    serverItem = {
      ...serverItem,
      purchased: !serverItem.purchased,
      version: serverItem.version + 1,
    };
    return Promise.resolve({ item: serverItem });
  });
  open(transport);
  const milk = await screen.findByRole("button", { name: /^Mark Milk as/ });
  await user.click(milk);
  // The Undo tap arrives behind the unanswered write.
  await user.click(milk);
  act(() => timeout());
  await waitFor(() => expect(purchase).toHaveBeenCalledTimes(3));
  // 1: the lost buy, 2: its replay with the same key, 3: the Undo against the replayed version.
  expect(keys[1]).toBe(keys[0]);
  expect(purchase.mock.calls[2]![0]).toMatchObject({
    purchased: true,
    version: 2,
  });
  await waitFor(() => expect(milk).toHaveAccessibleName(/as bought/));
  expect(serverItem.purchased).toBe(false);
});
