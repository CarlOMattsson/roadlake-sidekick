import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  COMPACT_ROWS,
  ShoppingView,
  compactGroups,
} from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { elementWithText } from "@tests/helpers/exact-text";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(n: number, over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    list_id: list.id,
    name: `Vara ${n}`,
    quantity: "1",
    unit: null,
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

// Twelve open items, one store: more than the compact view shows.
const twelve = Array.from({ length: 12 }, (_, index) => item(index + 1));

describe("compact inline view (a host without fullscreen)", () => {
  it("shows the first open rows under their store heading, then Show all (N) alone, and no Edit button", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    const showAll = await screen.findByRole("button", {
      name: shoppingEn.showAll(12),
    });
    expect(showAll).toHaveAttribute("aria-expanded", "false");
    // One store group: its heading takes one of the COMPACT_ROWS lines, the rows take the rest.
    expect(screen.getAllByRole("checkbox")).toHaveLength(COMPACT_ROWS - 1);
    // No separate "+N more" line: Show all (N) is the only control under the rows.
    expect(
      screen.queryByText(shoppingEn.moreItems(12 - (COMPACT_ROWS - 1))),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.edit }),
    ).not.toBeInTheDocument();
  });

  it("Show all expands the whole list in place; Show fewer folds it again", async () => {
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: shoppingEn.showAll(12) }),
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(12);
    const fewer = screen.getByRole("button", { name: shoppingEn.showFewer });
    expect(fewer).toHaveAttribute("aria-expanded", "true");
    // Expanded, the full view is back: the picker, the forms and the hint are shown again.
    expect(screen.getByText(shoppingEn.hint)).toBeInTheDocument();
    expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
    expect(screen.getByLabelText(shoppingEn.select)).toBeInTheDocument();
    await user.click(fewer);
    expect(screen.getAllByRole("checkbox")).toHaveLength(COMPACT_ROWS - 1);
    expect(screen.queryByText(shoppingEn.hint)).not.toBeInTheDocument();
  });

  it("a store heading takes a line of the budget, so three shops stay within COMPACT_ROWS lines", async () => {
    const shops = [
      item(1, { store: "ICA" }),
      item(2, { store: "ICA" }),
      item(3, { store: "Willys" }),
      item(4, { store: "Willys" }),
      item(5, { store: "Clas Ohlson" }),
      item(6, { store: "Clas Ohlson" }),
    ];
    render(
      <ShoppingView
        transport={adapter(detailOf(shops))}
        labels={shoppingEn}
        initial={detailOf(shops)}
        compact
      />,
    );
    await screen.findByRole("button", { name: shoppingEn.showAll(6) });
    const headings = screen.getAllByRole("heading", { level: 3 });
    const rows = screen.getAllByRole("checkbox");
    expect(headings.length).toBeGreaterThan(0);
    expect(headings.length).toBeLessThan(3);
    expect(headings.length + rows.length).toBeLessThanOrEqual(COMPACT_ROWS);
  });

  it("the folded view has no list picker, no Refresh, no create-list form and no hint", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    await screen.findByRole("button", { name: shoppingEn.showAll(12) });
    expect(
      screen.queryByLabelText(shoppingEn.listName),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(shoppingEn.select)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.refresh }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.hint)).not.toBeInTheDocument();
  });

  it("the list name is the card title under the Shopping eyebrow", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    const title = await screen.findByRole("heading", {
      level: 2,
      name: list.name,
    });
    expect(title).toHaveClass("sk-back-header__title");
    expect(
      screen.getByRole("heading", { level: 1, name: shoppingEn.title }),
    ).toHaveClass("sk-eyebrow");
  });

  it("the folded add field is one input with the Add button beside it, not a textarea", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    await screen.findByRole("button", { name: shoppingEn.showAll(12) });
    const field = screen.getByLabelText(shoppingEn.batchShort);
    expect(field.tagName).toBe("INPUT");
    expect(field.closest("form")?.querySelector("textarea")).toBeNull();
    expect(
      screen.getByRole("button", { name: shoppingEn.addItemButton }),
    ).toBeInTheDocument();
  });

  it("ticking an open row inline holds it as 'Bought · Undo'; Undo buys it back", async () => {
    const user = userEvent.setup();
    const transport = adapter(detailOf(twelve));
    transport.purchase = vi.fn((current: ShoppingItem) =>
      Promise.resolve({
        item: {
          ...current,
          purchased: !current.purchased,
          version: current.version + 1,
        },
      }),
    );
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    await user.click((await screen.findAllByRole("checkbox"))[0]!);
    const undo = await screen.findByRole("button", {
      name: shoppingEn.undoPurchaseNamed("Vara 1", true),
    });
    // The row holds in its place: its status line says "Bought", and Undo is a tonal button in the toolbar where
    // Edit stood. No meta line (.shopping-held) is used in the inline view.
    const row = undo.closest("li")!;
    expect(row).toHaveClass("shopping-held-item");
    expect(undo).toHaveClass("sk-btn--secondary", "sk-btn--compact");
    expect(undo.closest(".shopping-toolbar")).not.toBeNull();
    expect(row.querySelector(".shopping-status")).toHaveTextContent(
      shoppingEn.bought,
    );
    expect(row.querySelector(".shopping-held")).toBeNull();
    await user.click(undo);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", {
          name: shoppingEn.undoPurchaseNamed("Vara 1", true),
        }),
      ).not.toBeInTheDocument(),
    );
    expect(transport.purchase).toHaveBeenLastCalledWith(
      // Undo writes against the version that buying returned (version 2), not the re-read list.
      expect.objectContaining({ purchased: true, version: 2 }),
      expect.any(String),
    );
  });

  it("Enter in the folded add field adds the typed items", async () => {
    const user = userEvent.setup();
    const transport = adapter(detailOf(twelve));
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    const field = await screen.findByLabelText(shoppingEn.batchShort);
    await user.type(field, "Bread, Milk{Enter}");
    expect(transport.add).toHaveBeenCalledWith(
      list.id,
      ["Bread", "Milk"],
      expect.any(String),
    );
  });

  it("purchased items fold to one disclosure button with aria-expanded", async () => {
    const user = userEvent.setup();
    const items = [item(1), item(2), item(3, { purchased: true })];
    render(
      <ShoppingView
        transport={adapter(detailOf(items))}
        labels={shoppingEn}
        initial={detailOf(items)}
        compact
      />,
    );
    const toggle = await waitFor(() =>
      elementWithText(shoppingEn.boughtCount(1), "button"),
    );
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    // Folded: only the two open rows have a checkbox.
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    const checked = screen
      .getAllByRole("checkbox")
      .filter((box) => (box as HTMLInputElement).checked);
    expect(checked).toHaveLength(1);
  });

  it("a list that fits the compact rows shows no +N more and no Show all", async () => {
    const few = [item(1), item(2)];
    render(
      <ShoppingView
        transport={adapter(detailOf(few))}
        labels={shoppingEn}
        initial={detailOf(few)}
        compact
      />,
    );
    await screen.findAllByRole("checkbox");
    expect(screen.getAllByRole("checkbox")).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: /^Show all/ }),
    ).not.toBeInTheDocument();
  });

  it("without compact every open row is shown and there is no Show all", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
      />,
    );
    await screen.findAllByRole("checkbox");
    expect(screen.getAllByRole("checkbox")).toHaveLength(12);
    expect(
      screen.queryByRole("button", { name: shoppingEn.showAll(12) }),
    ).not.toBeInTheDocument();
    expect(
      screen.getAllByRole("button", { name: shoppingEn.edit }),
    ).toHaveLength(12);
  });
});

describe("compactGroups", () => {
  const groups: [string | null, string[]][] = [
    ["ICA", ["a", "b", "c"]],
    [null, ["d", "e"]],
  ];

  it("a shown group costs one line for its heading and one per row, in store order", () => {
    // Four lines: the ICA heading and its three rows. The second heading does not fit.
    expect(compactGroups(groups, 4).map((group) => group.shown)).toEqual([
      ["a", "b", "c"],
      [],
    ]);
    // Six lines: both headings, three rows and one row. Each group keeps its full row count.
    const result = compactGroups(groups, 6);
    expect(result.map((group) => group.shown)).toEqual([
      ["a", "b", "c"],
      ["d"],
    ]);
    expect(result.map((group) => group.rows.length)).toEqual([3, 2]);
  });

  it("a group whose heading and first row do not fit shows no rows", () => {
    expect(compactGroups(groups, 1).map((group) => group.shown)).toEqual([
      [],
      [],
    ]);
    expect(compactGroups(groups, 3)[1]!.shown).toEqual([]);
    expect(compactGroups(groups, 5)[1]!.shown).toEqual([]);
  });

  it("each one-row shop costs two lines, so a fifth line fits two shops", () => {
    const shops: [string | null, string[]][] = [
      ["A", ["a"]],
      ["B", ["b"]],
      ["C", ["c"]],
    ];
    expect(compactGroups(shops, 5).map((group) => group.shown)).toEqual([
      ["a"],
      ["b"],
      [],
    ]);
  });

  it("an unlimited limit shows all rows", () => {
    expect(
      compactGroups(groups, Infinity).flatMap((group) => group.shown),
    ).toHaveLength(5);
  });
});
