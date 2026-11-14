import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: "019f0000-0000-7000-8000-0000000000a0",
    list_id: list.id,
    name: "Milk",
    quantity: "2",
    unit: "l",
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

const milkId = "019f0000-0000-7000-8000-0000000000a1";
const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [item({ id: milkId, name: "Milk", version: 1 })],
};
// The same row after another device changed it: its version has moved on.
const refreshed: ShoppingDetail = {
  ...detail,
  items: [item({ id: milkId, name: "Milk", version: 2 })],
};

function adapter(over: Partial<ShoppingTransport> = {}): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(refreshed),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn().mockResolvedValue({}),
    update: vi.fn(),
    purchase: vi.fn().mockResolvedValue({}),
    ...over,
  };
}

async function waitLoaded() {
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
}

it("a conflict reads the list again, shows the change notice and offers no retry of the old version", async () => {
  const conflict = { code: "conflict" };
  const transport = adapter({
    purchase: vi
      .fn()
      .mockRejectedValueOnce(conflict)
      .mockResolvedValue({
        item: item({ id: milkId, purchased: true, version: 3 }),
      }),
  });
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitLoaded();

  await user.click(screen.getByRole("checkbox", { name: /Milk/ }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(shoppingEn.conflict),
  );
  // The old version is never sent again: no "Try again" for a refused write.
  expect(
    screen.queryByRole("button", { name: shoppingEn.retry }),
  ).not.toBeInTheDocument();
  // The list was read again, so the row carries the new version.
  await waitFor(() => expect(transport.get).toHaveBeenCalledTimes(1));
  await waitLoaded();

  // The next tap is a new write against the new version, with a new key.
  await user.click(screen.getByRole("checkbox", { name: /Milk/ }));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
  const [first, second] = vi.mocked(transport.purchase).mock.calls;
  expect(first![0].version).toBe(1);
  expect(second![0].version).toBe(2);
  expect(second![1]).not.toBe(first![1]);
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
});

it("an HTTP 409 counts as a conflict too", async () => {
  const transport = adapter({
    purchase: vi.fn().mockRejectedValueOnce({ status: 409 }),
  });
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitLoaded();

  await user.click(screen.getByRole("checkbox", { name: /Milk/ }));
  await waitFor(() =>
    expect(screen.getByRole("alert")).toHaveTextContent(shoppingEn.conflict),
  );
  expect(
    screen.queryByRole("button", { name: shoppingEn.retry }),
  ).not.toBeInTheDocument();
});

it("a failure that is not a conflict keeps the generic message and Try again", async () => {
  const transport = adapter({
    purchase: vi.fn().mockRejectedValueOnce(new Error("network down")),
  });
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitLoaded();

  await user.click(screen.getByRole("checkbox", { name: /Milk/ }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: shoppingEn.retry }),
    ).toBeInTheDocument(),
  );
  expect(screen.getByRole("alert")).not.toHaveTextContent(shoppingEn.conflict);
});
