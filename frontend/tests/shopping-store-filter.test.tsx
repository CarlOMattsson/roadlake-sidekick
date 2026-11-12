import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
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
    store: "ICA",
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

// What get_shopping_list answers for store "ICA": that shop's items plus the unmarked ones.
const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  store: "ICA",
  items: [
    item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" }),
    item({
      id: "019f0000-0000-7000-8000-0000000000a2",
      name: "Bread",
      store: null,
    }),
  ],
};

function adapter(): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn().mockResolvedValue({}),
  };
}

it("with a store the inline view shows large rows, reads with the filter and hides the forms", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      listId={list.id}
      store="ICA"
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(transport.get).toHaveBeenCalledWith(list.id, 0, "ICA");
  expect(
    screen.getByRole("button", { name: /^Mark Milk as/ }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: /^Mark Bread as/ }),
  ).toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.listName)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.batch)).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: /^Mark Milk as/ }));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
});

it("without a store the inline view keeps the full list view with its forms", async () => {
  const transport = adapter();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} listId={list.id} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(transport.get).toHaveBeenCalledWith(list.id, 0, undefined);
  expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
});
it("the shop view names its shop and the open count in the heading", async () => {
  const transport = adapter();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      store="ica"
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  // The spelling the items use wins over the spelling that was asked for.
  expect(
    screen.getByRole("heading", { level: 2, name: "ICA · 2 left" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 3, name: "No store" }),
  ).toBeInTheDocument();
});

it("the shop view heading follows the app language", async () => {
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingSv}
      initial={detail}
      store="ICA"
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(
    screen.getByRole("heading", { level: 2, name: "ICA · 2 kvar" }),
  ).toBeInTheDocument();
  expect(
    screen.getByRole("heading", { level: 3, name: "Utan butik" }),
  ).toBeInTheDocument();
});

it("a quantity of 1 without a unit is not shown in the shop view, an amount is", async () => {
  const withAmounts: ShoppingDetail = {
    ...detail,
    items: [
      item({
        id: "019f0000-0000-7000-8000-0000000000b1",
        name: "Eggs",
        quantity: "1.000",
        unit: "",
      }),
      item({
        id: "019f0000-0000-7000-8000-0000000000b2",
        name: "Butter",
        quantity: "2",
        unit: "",
      }),
    ],
  };
  const transport = adapter();
  vi.mocked(transport.get).mockResolvedValue(withAmounts);
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={withAmounts}
      store="ICA"
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  const eggs = screen.getByText("Eggs").closest("button")!;
  const butter = screen.getByText("Butter").closest("button")!;
  expect(eggs.querySelector(".shopping-store-qty")).toBeNull();
  expect(butter.querySelector(".shopping-store-qty")).toHaveTextContent("2");
});

it("the quick field adds to the shop that is open", async () => {
  const transport = adapter();
  vi.mocked(transport.add).mockResolvedValue({ items: [] } as never);
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      store="ICA"
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  // "+ Add item" opens the create field in the list; the field is the textbox with that name.
  await user.click(screen.getByRole("button", { name: shoppingEn.addItem }));
  await user.type(
    screen.getByRole("textbox", { name: shoppingEn.addItem }),
    "Eggs{Enter}",
  );
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  expect(vi.mocked(transport.add).mock.calls[0]![3]).toMatchObject({
    store: "ICA",
  });
});
