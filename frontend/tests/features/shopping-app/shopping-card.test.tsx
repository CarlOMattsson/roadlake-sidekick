import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import {
  cardItemText,
  formatQuantity,
  isDefaultAmount,
  quantityText,
} from "@/features/shopping-app/shopping-card";
import {
  COMPACT_ROWS,
  ShoppingView,
} from "@/features/shopping-app/shopping-view";
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
    store: null,
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

const names = ["Milk", "Bread", "Eggs", "Shelf", "Lamp", "Tea"];

function detailOf(items: ShoppingItem[]): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items,
  };
}

function adapter(detail: ShoppingDetail): ShoppingTransport {
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

/** The inline card the way the room draws it where fullscreen is on offer: the compact view with the open link. */
function card(
  detail: ShoppingDetail,
  labels = shoppingEn,
  onOpenFull: () => void = vi.fn(),
) {
  return render(
    <ShoppingView
      transport={adapter(detail)}
      labels={labels}
      initial={detail}
      compact
      onOpenFull={onOpenFull}
    />,
  );
}

const openRings = () =>
  screen.queryAllByRole("button", {
    name: /^(Mark .+ as bought|Markera .+ som köpt)$/,
  });

const sixOpen = names.map((name, index) =>
  item({ id: `019f0000-0000-7000-8000-0000000000${index + 10}`, name }),
);

it("shows the list name, the amounts as row text and counts the rows it leaves out in the open link", async () => {
  card(
    detailOf([
      ...sixOpen,
      item({
        id: "019f0000-0000-7000-8000-0000000000f0",
        name: "Coffee",
        purchased: true,
      }),
    ]),
  );
  expect(
    await screen.findByRole("heading", { name: "Weekly shopping" }),
  ).toBeInTheDocument();
  // The same row as everywhere: a ring, the name and the amount.
  expect(openRings()).toHaveLength(COMPACT_ROWS - 1);
  expect(
    screen.getByText("Milk", { selector: ".shopping-store-name" }),
  ).toBeInTheDocument();
  expect(
    screen
      .getByText("Milk", { selector: ".shopping-store-name" })
      .parentElement?.querySelector(".shopping-store-qty"),
  ).toHaveTextContent("2 l");
  expect(screen.queryByText("Tea")).not.toBeInTheDocument();
  expect(screen.queryByText("Coffee")).not.toBeInTheDocument();
  // What the card leaves out is counted in the link, after its name: "Open list · 2 more".
  expect(
    screen.getByRole("button", { name: /^Open list\s*· 2 more$/ }),
  ).toHaveTextContent(`${shoppingEn.openList} · ${shoppingEn.hiddenItems(2)}`);
  expect(screen.queryByText(shoppingEn.moreItems(2))).not.toBeInTheDocument();
});

it("counts the hidden open items in the open link, in both languages", async () => {
  const many = Array.from({ length: 6 }, (_, index) =>
    item({
      id: `019f0000-0000-7000-8000-0000000000${index + 20}`,
      name: "Ost",
    }),
  );
  const { unmount } = card(detailOf(many), shoppingSv);
  expect(
    await screen.findByRole("button", { name: /^Öppna listan\s*· 2 till$/ }),
  ).toHaveTextContent("Öppna listan · 2 till");
  unmount();
  card(detailOf(many), shoppingEn);
  expect(
    await screen.findByRole("button", { name: /^Open list\s*· 2 more$/ }),
  ).toHaveTextContent("Open list · 2 more");
});

it("says nothing about hidden items when all open items fit", async () => {
  card(detailOf(sixOpen.slice(0, 4)), shoppingSv);
  expect(
    await screen.findByRole("button", { name: shoppingSv.openList }),
  ).toBeInTheDocument();
  expect(screen.queryByText(/· \d+ till$/)).not.toBeInTheDocument();
});

it("draws no progress line for an empty list, which says what to ask for", async () => {
  card(detailOf([]), shoppingSv);
  expect(await screen.findByText(shoppingSv.empty)).toBeInTheDocument();
  expect(screen.queryByText(shoppingSv.boughtOf(0, 0))).not.toBeInTheDocument();
  expect(screen.queryByRole("progressbar")).not.toBeInTheDocument();
});

it("Open asks for fullscreen through the callback", async () => {
  const onOpenFull = vi.fn();
  const user = userEvent.setup();
  card(detailOf([item({})]), shoppingEn, onOpenFull);
  await user.click(
    await screen.findByRole("button", { name: shoppingEn.openList }),
  );
  expect(onOpenFull).toHaveBeenCalledTimes(1);
});

it("the room draws an inline list as this card where fullscreen is on offer, and its link requests fullscreen", async () => {
  const requestDisplayMode = vi.fn().mockResolvedValue("fullscreen");
  const transport: RoomTransport = {
    call: vi.fn(async () => new Promise(() => undefined)) as never,
    requestDisplayMode,
    updateModelContext: vi.fn(),
  };
  const user = userEvent.setup();
  render(
    <ShoppingRoom
      initial={detailOf(sixOpen)}
      resultId={1}
      mode="inline"
      fullscreenAvailable
      transport={transport}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: /^Open list\s*· 2 more$/ }),
  );
  expect(requestDisplayMode).toHaveBeenCalledWith("fullscreen");
  expect(screen.queryAllByRole("checkbox")).toHaveLength(0);
});

it("leaves out a quantity of one when the item has no unit", async () => {
  card(
    detailOf([
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
    ]),
  );
  const amountOf = (name: string) =>
    screen
      .getByText(name, { selector: ".shopping-store-name" })
      .parentElement?.querySelector(".shopping-store-qty");
  await screen.findByText("Havregryn");
  expect(amountOf("Havregryn")).toBeNull();
  expect(amountOf("Ägg")).toHaveTextContent("1 st");
  expect(amountOf("Bröd")).toHaveTextContent("2");
});

it("shows the formatted quantity in the row with the Swedish labels", async () => {
  card(detailOf([item({ quantity: "1.500", unit: "l" })]), shoppingSv);
  const name = await screen.findByText("Milk", {
    selector: ".shopping-store-name",
  });
  expect(
    name.parentElement?.querySelector(".shopping-store-qty"),
  ).toHaveTextContent("1,5 l");
});

it("cardItemText leaves the default amount out and keeps a unit's one", () => {
  expect(cardItemText(item({ quantity: "1", unit: null }), "sv-SE")).toBe(
    "Milk",
  );
  expect(cardItemText(item({ quantity: "1", unit: "st" }), "sv-SE")).toBe(
    "Milk · 1 st",
  );
  expect(cardItemText(item({ quantity: "2", unit: "l" }), "en-GB")).toBe(
    "Milk · 2 l",
  );
  expect(
    isDefaultAmount(item({ quantity: "1.000", unit: null }), "en-GB"),
  ).toBe(true);
  expect(isDefaultAmount(item({ quantity: "1", unit: "st" }), "en-GB")).toBe(
    false,
  );
});

it("the list picker's open link names the shopping, counts nothing and opens", async () => {
  const onOpen = vi.fn();
  const user = userEvent.setup();
  const transport = adapter(detailOf([]));
  vi.mocked(transport.lists).mockResolvedValue({
    lists: [
      { ...list, open_count: 1 },
      {
        ...list,
        id: `${list.id.slice(0, -1)}2`,
        name: "Garden",
        open_count: 3,
      },
    ],
    next_offset: null,
  });
  const { unmount } = render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      onOpenFull={onOpen}
    />,
  );
  const open = await screen.findByRole("button", {
    name: shoppingEn.openShopping,
  });
  expect(open).toHaveClass("sk-open-link");
  expect(open).toHaveTextContent(new RegExp(`^${shoppingEn.openShopping}$`));
  await user.click(open);
  expect(onOpen).toHaveBeenCalledTimes(1);
  unmount();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingSv}
      onOpenFull={onOpen}
    />,
  );
  expect(
    await screen.findByRole("button", { name: shoppingSv.openShopping }),
  ).toHaveClass("sk-open-link");
});

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

afterAll(() => {
  document.head.innerHTML = "";
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
