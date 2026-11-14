import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import {
  formatQuantity,
  quantityText,
  ShoppingCard,
} from "@/features/shopping-app/shopping-card";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
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

const names = ["Milk", "Bread", "Eggs", "Shelf", "Lamp", "Tea"];

it("shows the list name, the open count and only the first four open items as text", () => {
  const detail: ShoppingDetail = {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: [
      ...names.map((name, index) =>
        item({ id: `019f0000-0000-7000-8000-0000000000${index + 10}`, name }),
      ),
      item({
        id: "019f0000-0000-7000-8000-0000000000f0",
        name: "Coffee",
        purchased: true,
      }),
    ],
  };
  render(<ShoppingCard detail={detail} labels={shoppingEn} onOpen={vi.fn()} />);
  expect(
    screen.getByRole("heading", { name: "Weekly shopping" }),
  ).toBeInTheDocument();
  expect(screen.getByText(shoppingEn.boughtOf(1, 7))).toBeInTheDocument();
  expect(screen.getAllByRole("listitem")).toHaveLength(4);
  expect(screen.getByText("Milk · 2 l")).toBeInTheDocument();
  expect(screen.getByText("Shelf · 2 l")).toBeInTheDocument();
  expect(screen.queryByText(/^Lamp/)).not.toBeInTheDocument();
  expect(screen.queryByText(/^Coffee/)).not.toBeInTheDocument();
  // What the card leaves out is counted in the foot link, after its name: "Open list · 2 more".
  expect(
    screen.getByRole("button", { name: /^Open list\s*· 2 more$/ }),
  ).toHaveTextContent(`${shoppingEn.openList} · ${shoppingEn.hiddenItems(2)}`);
  expect(screen.queryByText(shoppingEn.moreItems(2))).not.toBeInTheDocument();
});

it("says nothing about hidden items when all open items are listed", () => {
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: names.slice(0, 4).map((name, index) =>
          item({
            id: `019f0000-0000-7000-8000-0000000000${index + 10}`,
            name,
          }),
        ),
      }}
      labels={shoppingSv}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getAllByRole("listitem")).toHaveLength(4);
  expect(
    screen.getByRole("button", { name: shoppingSv.openList }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/ fler$/)).not.toBeInTheDocument();
});

it("counts the hidden open items in the foot link, in both languages", () => {
  const many = Array.from({ length: 6 }, (_, index) =>
    item({
      id: `019f0000-0000-7000-8000-0000000000${index + 20}`,
      name: "Ost",
    }),
  );
  const detail = {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: many,
  };
  const { unmount } = render(
    <ShoppingCard detail={detail} labels={shoppingSv} onOpen={vi.fn()} />,
  );
  expect(
    screen.getByRole("button", { name: /^Öppna listan\s*· 2 fler$/ }),
  ).toHaveTextContent("Öppna listan · 2 fler");
  unmount();
  render(<ShoppingCard detail={detail} labels={shoppingEn} onOpen={vi.fn()} />);
  expect(
    screen.getByRole("button", { name: /^Open list\s*· 2 more$/ }),
  ).toHaveTextContent("Open list · 2 more");
});

it("draws no progress line for an empty list", () => {
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: [],
      }}
      labels={shoppingSv}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText(shoppingSv.empty)).toBeInTheDocument();
  expect(screen.queryByText(shoppingSv.boughtOf(0, 0))).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

it("Open asks for fullscreen through the callback", async () => {
  const onOpen = vi.fn();
  const user = userEvent.setup();
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: [item({})],
      }}
      labels={shoppingEn}
      onOpen={onOpen}
    />,
  );
  await user.click(screen.getByRole("button", { name: shoppingEn.openList }));
  expect(onOpen).toHaveBeenCalledTimes(1);
});

it("says that everything is bought when no open item is left", () => {
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: [item({ purchased: true })],
      }}
      labels={shoppingEn}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText(shoppingEn.boughtOf(1, 1))).toBeInTheDocument();
  expect(screen.getByText(shoppingEn.allBought)).toBeInTheDocument();
  expect(screen.queryByRole("listitem")).not.toBeInTheDocument();
});

it("reads decimal string quantities without trailing zeros in the list locale", () => {
  expect(formatQuantity("1.000", "en-GB")).toBe("1");
  expect(formatQuantity("1.5", "en-GB")).toBe("1.5");
  expect(formatQuantity("1.5", "sv-SE")).toBe("1,5");
  expect(formatQuantity("1.250", "sv-SE")).toBe("1,25");
  expect(formatQuantity("12.000", "sv-SE")).toBe("12");
  expect(formatQuantity(3, "en-GB")).toBe("3");
});

it("returns a value that is not a plain decimal unchanged", () => {
  expect(formatQuantity("abc", "sv-SE")).toBe("abc");
  expect(formatQuantity("1e3", "en-GB")).toBe("1e3");
  expect(formatQuantity("", "en-GB")).toBe("");
});

it("quantityText adds the unit after the formatted number", () => {
  expect(quantityText(item({ quantity: "12.000", unit: "st" }), "sv-SE")).toBe(
    "12 st",
  );
  expect(quantityText(item({ quantity: "1.000", unit: null }))).toBe("1");
  expect(quantityText(item({ quantity: "1.500", unit: "l" }), "sv-SE")).toBe(
    "1,5 l",
  );
  expect(quantityText(item({ quantity: "1.500", unit: "l" }))).toBe("1.5 l");
});

it("counts a unitless quantity in pieces: st in Swedish, the bare number otherwise", () => {
  expect(quantityText(item({ quantity: "8", unit: null }), "sv-SE")).toBe(
    "8 st",
  );
  expect(quantityText(item({ quantity: "8", unit: null }), "en-GB")).toBe("8");
});

it("leaves out a quantity of one when the item has no unit", () => {
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: [
          item({
            id: "019f0000-0000-7000-8000-0000000000b1",
            name: "Havregryn",
            quantity: "1.000",
            unit: null,
          }),
          item({
            id: "019f0000-0000-7000-8000-0000000000b2",
            name: "Ägg",
            quantity: "1",
            unit: "st",
          }),
          item({
            id: "019f0000-0000-7000-8000-0000000000b3",
            name: "Bröd",
            quantity: "2",
            unit: null,
          }),
        ],
      }}
      labels={shoppingEn}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText("Havregryn")).toBeInTheDocument();
  expect(screen.queryByText("Havregryn · 1")).not.toBeInTheDocument();
  expect(screen.getByText("Ägg · 1 st")).toBeInTheDocument();
  expect(screen.getByText("Bröd · 2")).toBeInTheDocument();
});

it("shows the formatted quantity in the card with the Swedish labels", () => {
  render(
    <ShoppingCard
      detail={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: [item({ quantity: "1.500", unit: "l" })],
      }}
      labels={shoppingSv}
      onOpen={vi.fn()}
    />,
  );
  expect(screen.getByText("Milk · 1,5 l")).toBeInTheDocument();
});
