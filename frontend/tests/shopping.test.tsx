import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import {
  formatPriceNumber,
  formatQuantityNumber,
  parsePriceInput,
  parseQuantityInput,
} from "@/features/shopping-app/shopping-view-parts/helpers";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { elementWithText } from "./helpers/exact-text";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "IKEA someday",
  version: 1,
  archived: false,
  open_count: 0,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const detail: ShoppingDetail = {
  shopping_list: list,
  items: [],
  next_offset: null,
  evaluated_on: "2026-10-24",
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
    purchase: vi.fn(),
  };
}

it("keeps an uncertain batch retry on the same write identity", async () => {
  const transport = adapter();
  const add = vi
    .mocked(transport.add)
    .mockRejectedValueOnce(new Error("PRIVATE_BACKEND_MESSAGE"))
    .mockResolvedValueOnce({});
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.type(screen.getByLabelText(shoppingEn.batch), "Shelf\nLamp");
  await user.click(screen.getByRole("button", { name: shoppingEn.add }));
  expect(await screen.findByRole("alert")).toHaveTextContent(shoppingEn.failed);
  expect(screen.queryByText("PRIVATE_BACKEND_MESSAGE")).not.toBeInTheDocument();
  await user.click(screen.getByRole("button", { name: shoppingEn.add }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(2));
  expect(add.mock.calls[0]).toEqual(add.mock.calls[1]);
  expect(add.mock.calls[0]![1]).toEqual(["Shelf", "Lamp"]);
});

it("does not turn failed reads into an empty shopping list", async () => {
  const transport = adapter();
  vi.mocked(transport.get)
    .mockRejectedValueOnce(new Error("PRIVATE"))
    .mockResolvedValue(detail);
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} listId={list.id} />,
  );
  expect(await screen.findByRole("alert")).toHaveTextContent(shoppingEn.failed);
  await user.click(
    screen.getAllByRole("button", { name: shoppingEn.refresh })[0]!,
  );
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
  expect(transport.get).toHaveBeenCalledTimes(2);
});

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

it("groups open items by store and keeps purchased items in a collapsed section", () => {
  const transport = adapter();
  const withItems: ShoppingDetail = {
    ...detail,
    items: [
      item({
        id: "019f0000-0000-7000-8000-0000000000a1",
        name: "Milk",
        store: "ICA MAXI 4",
      }),
      item({
        id: "019f0000-0000-7000-8000-0000000000a2",
        name: "Shelf",
        store: "IKEA",
      }),
      item({
        id: "019f0000-0000-7000-8000-0000000000a3",
        name: "Bread",
        store: "ICA MAXI 4",
      }),
      item({
        id: "019f0000-0000-7000-8000-0000000000a4",
        name: "Lamp",
        store: null,
      }),
      item({
        id: "019f0000-0000-7000-8000-0000000000a5",
        name: "Eggs",
        store: "ICA MAXI 4",
        purchased: true,
      }),
    ],
  };
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={withItems}
    />,
  );
  const headings = screen
    .getAllByRole("heading", { level: 3 })
    .map((heading) => heading.textContent);
  // Open items without a store get their own heading, so they never sit under a store heading.
  // Store headings carry no count: the name alone.
  expect(headings).toEqual(["ICA MAXI 4", "IKEA", "No store"]);
  const fold = elementWithText(`${shoppingEn.purchased} (1)`, "button");
  expect(fold).toHaveClass("sk-fold");
  expect(fold).toHaveAttribute("aria-expanded", "false");
  expect(fold.closest("div")).toHaveClass("shopping-purchased");
  expect(document.querySelector("details.shopping-purchased")).toBeNull();
  // The purchased item is drawn when the fold is opened.
  fireEvent.click(fold);
  expect(fold).toHaveAttribute("aria-expanded", "true");
  // The store is shown once, in the group heading. Only the purchased item, which has no heading, repeats it.
  expect(screen.getAllByText(`${shoppingEn.store}: ICA MAXI 4`)).toHaveLength(
    1,
  );
});

it("shows the regular price and calendar dates without the form label or ISO dates", () => {
  const transport = adapter();
  const withOffer: ShoppingDetail = {
    ...detail,
    items: [
      item({
        name: "Milk",
        store: "ICA MAXI 4",
        offer_status: "current",
        offer: {
          price: "14.90",
          regular_price: "17.90",
          currency: "SEK",
          valid_from: "2026-10-23",
          valid_until: "2026-10-30",
          checked_on: "2026-10-25",
          source: "ICA",
          source_url: null,
        },
      }),
    ],
  };
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={withOffer}
    />,
  );
  expect(screen.queryByText(shoppingEn.regular)).not.toBeInTheDocument();
  expect(screen.getByText(/Regular price: 17\.90/)).toBeInTheDocument();
  expect(screen.getByText(/23 Oct 2026 – 30 Oct 2026/)).toBeInTheDocument();
  expect(screen.getByText(/Date checked: 25 Oct 2026/)).toBeInTheDocument();
  expect(screen.queryByText(/2026-10-2\d/)).not.toBeInTheDocument();
});

it("creates a list when Enter is pressed in the list name field", async () => {
  const transport = adapter();
  const create = vi
    .mocked(transport.create)
    .mockResolvedValue({ shopping_list: list });
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.type(screen.getByLabelText(shoppingEn.listName), "Garden{Enter}");
  await waitFor(() => expect(create).toHaveBeenCalledTimes(1));
  expect(create.mock.calls[0]![0]).toBe("Garden");
});

it("adds a comma separated batch as separate names", async () => {
  const transport = adapter();
  const add = vi.mocked(transport.add).mockResolvedValue({});
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.type(screen.getByLabelText(shoppingEn.batch), "Mjölk, bröd,\nägg");
  await user.click(screen.getByRole("button", { name: shoppingEn.add }));
  await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
  expect(add.mock.calls[0]![1]).toEqual(["Mjölk", "bröd", "ägg"]);
});

it("adds the batch when Enter is pressed in the field, and Shift+Enter keeps a line break", async () => {
  const transport = adapter();
  const add = vi.mocked(transport.add).mockResolvedValue({});
  const user = userEvent.setup();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  const batch = screen.getByLabelText(shoppingEn.batch);
  await user.type(batch, "Shelf{Shift>}{Enter}{/Shift}Lamp");
  expect(batch).toHaveValue("Shelf\nLamp");
  expect(add).not.toHaveBeenCalled();
  await user.type(batch, "{Enter}");
  await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
  expect(add.mock.calls[0]![1]).toEqual(["Shelf", "Lamp"]);
  await waitFor(() => expect(batch).toHaveValue(""));
});

it("writes the offer's prices in the list's decimal style in the detail lines", () => {
  const withOffer: ShoppingDetail = {
    ...detail,
    items: [
      item({
        name: "Mjölk",
        offer_status: "current",
        offer: {
          price: "14.9",
          regular_price: "17.90",
          currency: "SEK",
          valid_from: "2026-10-23",
          valid_until: "2026-10-30",
          checked_on: "2026-10-25",
          source: "ICA",
          source_url: null,
        },
      }),
    ],
  };
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingSv}
      initial={withOffer}
    />,
  );
  expect(screen.getByText(/14,90 SEK/)).toBeInTheDocument();
  expect(screen.getByText(/Ordinarie pris: 17,90/)).toBeInTheDocument();
});

describe("price text helpers", () => {
  it("formats a stored price in the locale's decimal style", () => {
    expect(formatPriceNumber("19.9", "sv-SE")).toBe("19,90");
    expect(formatPriceNumber("19.9", "en-GB")).toBe("19.90");
    expect(formatPriceNumber("199.00", "sv-SE")).toBe("199");
    expect(formatPriceNumber("1234.5", "sv-SE")).toBe("1234,50");
    expect(formatPriceNumber("n/a", "sv-SE")).toBe("n/a");
  });

  it("reads a typed price with a comma or a point, within the limits", () => {
    expect(parsePriceInput("19,90")).toBe("19.90");
    expect(parsePriceInput(" 19.9 ")).toBe("19.9");
    expect(parsePriceInput("199")).toBe("199");
    expect(parsePriceInput("0")).toBeNull();
    expect(parsePriceInput("1,234")).toBeNull();
    expect(parsePriceInput("1,2,3")).toBeNull();
    expect(parsePriceInput("-5")).toBeNull();
    expect(parsePriceInput("100000000")).toBeNull();
    expect(parsePriceInput("")).toBeNull();
  });
});

describe("quantity text helpers", () => {
  it("formats a stored quantity without empty decimals, in the locale's style", () => {
    expect(formatQuantityNumber("2.000", "sv-SE")).toBe("2");
    expect(formatQuantityNumber("1.500", "sv-SE")).toBe("1,5");
    expect(formatQuantityNumber("1.500", "en-GB")).toBe("1.5");
    expect(formatQuantityNumber("0.125", "sv-SE")).toBe("0,125");
    expect(formatQuantityNumber("12000.000", "sv-SE")).toBe("12000");
    expect(formatQuantityNumber("n/a", "sv-SE")).toBe("n/a");
  });

  it("reads a typed quantity with a comma or a point, within the limits", () => {
    expect(parseQuantityInput("1,5")).toBe("1.5");
    expect(parseQuantityInput(" 2.25 ")).toBe("2.25");
    expect(parseQuantityInput("12")).toBe("12");
    expect(parseQuantityInput("0.001")).toBe("0.001");
    expect(parseQuantityInput("999999.999")).toBe("999999.999");
    expect(parseQuantityInput("0")).toBeNull();
    expect(parseQuantityInput("1,2345")).toBeNull();
    expect(parseQuantityInput("1,2,3")).toBeNull();
    expect(parseQuantityInput("-1")).toBeNull();
    expect(parseQuantityInput("1000000")).toBeNull();
    expect(parseQuantityInput("")).toBeNull();
  });
});
