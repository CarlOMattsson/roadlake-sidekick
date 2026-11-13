import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import { elementWithText } from "./helpers/exact-text";
import { itemMeta } from "@/features/shopping-app/shopping-view-parts/helpers";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// The store view's details: the archived list that explains itself, the one-line meta of a row, the finished list,
// and the rooms that give the empty states a real Claude action.
const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 3,
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

const offer = {
  price: "199.00",
  regular_price: "289.00",
  currency: "SEK",
  valid_from: "2026-11-01",
  valid_until: "2026-11-30",
  checked_on: "2026-11-05",
  source: "ica.se",
  source_url: null,
};

const rich = item({
  id: "019f0000-0000-7000-8000-0000000000a1",
  name: "Oat drink",
  occasion: "Birthday",
  target_date: "2026-11-20",
  note: "The blue carton",
  offer,
  offer_status: "current",
});

function detailOf(
  items: ShoppingItem[],
  over: Partial<ShoppingDetail> = {},
): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-11-10",
    next_offset: null,
    items,
    ...over,
  };
}

function adapter(): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detailOf([])),
    create: vi.fn(),
    rename: vi.fn().mockResolvedValue({}),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
  };
}

async function settled() {
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
}

/** Intl joins a currency with a no-break space: tests read it as a plain one. */
const plain = (text: string) => text.replace(/\u00a0/g, " ");

describe("itemMeta", () => {
  it("joins offer, date, occasion and note in the app language", () => {
    expect(plain(itemMeta(rich, shoppingEn))).toMatch(
      /^SEK ?199 \(was SEK ?289\) · by 20 Nov · Birthday · The blue carton$/,
    );
    expect(plain(itemMeta(rich, shoppingSv))).toMatch(
      /^199 kr \(ord\. 289 kr\) · till 20 nov · Birthday · The blue carton$/,
    );
  });

  it("keeps real decimals and marks an offer that does not apply today", () => {
    const meta = itemMeta(
      item({
        offer: { ...offer, price: "19.50", regular_price: null },
        offer_status: "expired",
      }),
      shoppingSv,
    );
    expect(plain(meta)).toMatch(/^19,50 kr · utgånget$/);
  });

  it("is empty for an item with no details", () => {
    expect(itemMeta(item({}), shoppingEn)).toBe("");
  });
});

describe("the store view", () => {
  it("shows an open row's details under its name, and none for a bought row", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detailOf([
          rich,
          item({
            id: "019f0000-0000-7000-8000-0000000000a2",
            name: "Rice",
            purchased: true,
            note: "Basmati",
          }),
        ])}
        fullscreen
      />,
    );
    await settled();
    const row = screen.getByText("Oat drink").closest("li")!;
    expect(row).toHaveTextContent("The blue carton");
    expect(row.querySelector(".shopping-store-meta")).not.toBeNull();
    // The bought row sits under the folded "Bought" group and is not drawn open.
    expect(screen.queryByText("Basmati")).not.toBeInTheDocument();
  });

  it("an archived list says so and offers Restore, which unarchives it", async () => {
    const transport = adapter();
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf([rich], {
          shopping_list: { ...list, archived: true },
        })}
        fullscreen
      />,
    );
    await settled();
    expect(screen.getByText(shoppingEn.archived)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: shoppingEn.restore }));
    await waitFor(() => expect(transport.rename).toHaveBeenCalledTimes(1));
    const [sent, name, archived] = vi.mocked(transport.rename).mock.calls[0]!;
    expect(sent.id).toBe(list.id);
    expect(name).toBe(list.name);
    expect(archived).toBe(false);
  });

  it("an active list has no archive button in the store view", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detailOf([rich])}
        fullscreen
      />,
    );
    await settled();
    expect(
      screen.queryByRole("button", { name: shoppingEn.archive }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.archived)).not.toBeInTheDocument();
  });

  it("says the list is done when every item is bought", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingSv}
        initial={detailOf([item({ purchased: true })])}
        fullscreen
      />,
    );
    await settled();
    expect(screen.getByText(shoppingSv.allBought)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Köpta/ })).toBeInTheDocument();
  });

  it("does not repeat the shop's own heading under a shop view's title", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detailOf(
          [
            item({ id: "019f0000-0000-7000-8000-0000000000b1" }),
            item({
              id: "019f0000-0000-7000-8000-0000000000b2",
              name: "Bread",
              store: null,
            }),
          ],
          { store: "ICA" },
        )}
        store="ICA"
        fullscreen
      />,
    );
    await settled();
    expect(
      screen.getByRole("heading", { level: 2, name: "ICA · 2 left" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("heading", { level: 3, name: "ICA" }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: "No store" }),
    ).toBeInTheDocument();
  });

  it("the change form shows an offer price without empty decimals and keeps its legend for screen readers", async () => {
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingSv}
        initial={detailOf([rich])}
        fullscreen
      />,
    );
    await settled();
    await user.click(screen.getByText("Oat drink"));
    const form = (await screen.findByRole("group", { name: /Redigera/ }))
      .parentElement!;
    expect(within(form).getByLabelText(shoppingSv.price)).toHaveDisplayValue(
      "199",
    );
    expect(within(form).getByLabelText(shoppingSv.regular)).toHaveDisplayValue(
      "289",
    );
    expect(screen.getByText(`${shoppingSv.edit}: Oat drink`)).toHaveClass(
      "shopping-visually-hidden",
    );
  });
});

describe("the list picker", () => {
  it("puts archived lists last, behind a fold", async () => {
    const user = userEvent.setup();
    const entry = (id: string, name: string, archived: boolean) => ({
      ...list,
      id,
      name,
      archived,
      open_count: 1,
    });
    const transport = adapter();
    transport.lists = vi.fn().mockResolvedValue({
      lists: [
        entry("019f0000-0000-7000-8000-0000000000c1", "Old gifts", true),
        entry("019f0000-0000-7000-8000-0000000000c2", "Weekly", false),
      ],
      next_offset: null,
    });
    render(<ShoppingView transport={transport} labels={shoppingEn} />);
    await screen.findByRole("button", { name: /^Weekly/ });
    await user.click(elementWithText(shoppingEn.archivedLists(1), "button"));
    const rows = screen.getAllByRole("button", {
      name: /Weekly|Old gifts/,
    });
    expect(rows.map((row) => row.textContent)).toEqual([
      expect.stringContaining("Weekly"),
      expect.stringContaining("Old gifts"),
    ]);
    // The fold stands between the active list and the archived one.
    expect(
      rows[0]!.compareDocumentPosition(
        elementWithText(shoppingEn.archivedLists(1), "button"),
      ) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
  });

  it("writes 'updated' with a lowercase day in English too", () => {
    expect(shoppingEn.listUpdated("Yesterday")).toBe("updated yesterday");
    expect(shoppingSv.listUpdated("Igår")).toBe("uppdaterad igår");
  });
});

describe("the room's empty state", () => {
  beforeAll(() => {
    document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  });
  afterAll(() => {
    document.head.innerHTML = "";
  });

  it("fullscreen with no lists sends the example to Claude through the host", async () => {
    const user = userEvent.setup();
    const sendMessage = vi.fn().mockResolvedValue(true);
    const transport: RoomTransport = {
      call: vi.fn(async (name: string) => {
        if (name === "list_shopping_lists")
          return { lists: [], next_offset: null };
        return new Promise(() => undefined);
      }) as unknown as RoomTransport["call"],
      requestDisplayMode: vi
        .fn()
        .mockResolvedValue(
          "fullscreen",
        ) as unknown as RoomTransport["requestDisplayMode"],
      updateModelContext:
        vi.fn() as unknown as RoomTransport["updateModelContext"],
    };
    const props: RoomProps = {
      initial: { lists: [], next_offset: null },
      resultId: 1,
      mode: "full",
      transport,
      sendMessage,
    };
    render(<ShoppingRoom {...props} />);
    await user.click(
      await screen.findByRole("button", {
        name: `Send to Claude: ${shoppingEn.emptyListsExample}`,
      }),
    );
    expect(sendMessage).toHaveBeenCalledWith(shoppingEn.emptyListsExample);
  });
});
