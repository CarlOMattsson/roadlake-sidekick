import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  COMPACT_ROWS,
  ShoppingView,
  compactGroups,
} from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
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

/** The open rows: one ring per open item ("Mark Vara 1 as bought"), the same row in every mode. */
function openRows() {
  return screen.queryAllByRole("button", { name: /^Mark .+ as bought$/ });
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
    expect(openRows()).toHaveLength(COMPACT_ROWS - 1);
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
    expect(openRows()).toHaveLength(12);
    const fewer = screen.getByRole("button", { name: shoppingEn.showFewer });
    expect(fewer).toHaveAttribute("aria-expanded", "true");
    await user.click(fewer);
    expect(openRows()).toHaveLength(COMPACT_ROWS - 1);
  });

  it("Show all reveals the remaining open rows with their steps and menu, but no list forms, hint or archive button", async () => {
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    // Folded, the card has no Edit button, and the rows are the same rows as everywhere (ring, amount). The card
    // is one phone screen, so the - + steps wait behind Show all (one-screen-mcp-app.spec.ts measures it).
    await screen.findByRole("button", { name: shoppingEn.showAll(12) });
    expect(
      screen.queryByRole("button", { name: shoppingEn.edit }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: shoppingEn.markBought("Vara 1") }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", {
        name: shoppingEn.increaseQuantity("Vara 1"),
      }),
    ).not.toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: shoppingEn.showAll(12) }),
    );
    expect(openRows()).toHaveLength(12);
    for (const n of [1, 12]) {
      expect(
        screen.getByRole("button", {
          name: shoppingEn.increaseQuantity(`Vara ${n}`),
        }),
      ).toBeInTheDocument();
    }
    expect(
      screen.queryByLabelText(shoppingEn.listName),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("combobox", { name: shoppingEn.list }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.hint)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.archive }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.refresh }),
    ).not.toBeInTheDocument();
  });

  it("the ⋯ menu's Edit list shows the rename field and the archive button, and every row uncapped", async () => {
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    await screen.findByRole("button", { name: shoppingEn.showAll(12) });
    expect(openRows()).toHaveLength(COMPACT_ROWS - 1);
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: shoppingEn.editList }));
    expect(screen.getByLabelText(shoppingEn.listName)).toHaveValue(list.name);
    expect(
      screen.getByRole("button", { name: shoppingEn.archive }),
    ).toBeInTheDocument();
    expect(openRows()).toHaveLength(12);
  });

  it("with an archived list the rename Save button is disabled", async () => {
    const user = userEvent.setup();
    const archivedDetail: ShoppingDetail = {
      ...detailOf(twelve),
      shopping_list: { ...list, archived: true },
    };
    render(
      <ShoppingView
        transport={adapter(archivedDetail)}
        labels={shoppingEn}
        initial={archivedDetail}
        compact
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: shoppingEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: shoppingEn.editList }));
    expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: shoppingEn.save }),
    ).toBeDisabled();
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
    const rows = openRows();
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
    await user.click(
      (
        await screen.findAllByRole("button", { name: /^Mark .+ as bought$/ })
      )[0]!,
    );
    const undo = await screen.findByRole("button", {
      name: shoppingEn.undoPurchaseNamed("Vara 1", true),
    });
    // The row holds in its place, as the store view's row does: Undo is a tonal button in the row, the held word
    // ("Bought") stands in the name line and the row's polite status says it too.
    const row = undo.closest("li")!;
    expect(row).toHaveClass("shopping-held-item", "shopping-store-item");
    expect(undo).toHaveClass("sk-btn--secondary", "sk-btn--compact");
    expect(row.querySelector(".shopping-held")).toHaveTextContent(
      shoppingEn.bought,
    );
    expect(within(row).getByRole("status")).toHaveTextContent(/Vara 1/);
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
      [{ name: "Bread" }, { name: "Milk" }],
      expect.any(String),
      expect.objectContaining({ mergeDuplicates: true }),
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
    // Folded: only the two open rows have a ring, and the bought one is not drawn.
    expect(openRows()).toHaveLength(2);
    expect(
      screen.queryByRole("button", { name: shoppingEn.markOpen("Vara 3") }),
    ).not.toBeInTheDocument();
    await user.click(toggle);
    expect(toggle).toHaveAttribute("aria-expanded", "true");
    // The bought row is a plain row under the fold, its ring offering to open it again.
    expect(
      screen.getByRole("button", { name: shoppingEn.markOpen("Vara 3") }),
    ).toBeInTheDocument();
    expect(openRows()).toHaveLength(2);
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
    await screen.findAllByRole("button", { name: /^Mark .+ as bought$/ });
    expect(openRows()).toHaveLength(2);
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
    await screen.findAllByRole("button", { name: /^Mark .+ as bought$/ });
    expect(openRows()).toHaveLength(12);
    expect(
      screen.queryByRole("button", { name: shoppingEn.showAll(12) }),
    ).not.toBeInTheDocument();
    // The same row component: every open row has its own amount steps.
    expect(
      screen.getAllByRole("button", { name: /^Increase quantity of Vara / }),
    ).toHaveLength(12);
  });
});

describe("compact inline view with fullscreen on offer", () => {
  it("ends on the open link with the number of rows it leaves out, and asks for fullscreen", async () => {
    const user = userEvent.setup();
    const onOpenFull = vi.fn();
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
        onOpenFull={onOpenFull}
      />,
    );
    const hidden = 12 - (COMPACT_ROWS - 1);
    const open = await screen.findByRole("button", {
      name: new RegExp(`^Open list\\s*· ${hidden} more$`),
    });
    expect(open).toHaveTextContent(
      `${shoppingEn.openList} · ${shoppingEn.hiddenItems(hidden)}`,
    );
    expect(openRows()).toHaveLength(COMPACT_ROWS - 1);
    // The link replaces "Show all": the card never grows in place.
    expect(
      screen.queryByRole("button", { name: shoppingEn.showAll(12) }),
    ).not.toBeInTheDocument();
    await user.click(open);
    expect(onOpenFull).toHaveBeenCalledTimes(1);
  });

  it("reads the same in Swedish", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingSv}
        initial={detailOf(twelve)}
        compact
        onOpenFull={() => undefined}
      />,
    );
    const hidden = 12 - (COMPACT_ROWS - 1);
    expect(
      await screen.findByRole("button", {
        name: new RegExp(`^Öppna listan\\s*· ${hidden} fler$`),
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingSv.showAll(12) }),
    ).not.toBeInTheDocument();
  });

  it("a list that fits still ends on the plain link, with no count", async () => {
    const few = [item(1), item(2)];
    render(
      <ShoppingView
        transport={adapter(detailOf(few))}
        labels={shoppingEn}
        initial={detailOf(few)}
        compact
        onOpenFull={() => undefined}
      />,
    );
    const open = await screen.findByRole("button", {
      name: shoppingEn.openList,
    });
    expect(open).not.toHaveTextContent("more");
  });

  it("leaves the bought rows to the full list: no 'Bought' fold in the card", async () => {
    const items = [item(1), item(2, { purchased: true })];
    render(
      <ShoppingView
        transport={adapter(detailOf(items))}
        labels={shoppingEn}
        initial={detailOf(items)}
        compact
        onOpenFull={() => undefined}
      />,
    );
    await screen.findByRole("button", { name: shoppingEn.openList });
    expect(
      screen.queryByText(shoppingEn.boughtCount(1)),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.markOpen("Vara 2") }),
    ).not.toBeInTheDocument();
  });

  it("without fullscreen on offer there is no open link, only Show all", async () => {
    render(
      <ShoppingView
        transport={adapter(detailOf(twelve))}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
      />,
    );
    expect(
      await screen.findByRole("button", { name: shoppingEn.showAll(12) }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Open list/ }),
    ).not.toBeInTheDocument();
  });

  it("an item just added shows at once in the folded card, also past the row budget", async () => {
    const user = userEvent.setup();
    const added = item(13, { name: "Bread" });
    const transport = adapter(detailOf(twelve));
    transport.add = vi
      .fn()
      .mockResolvedValue({ items: [{ item: added, merged: false }] });
    // The re-read after the write already holds the new row, as the last of 13.
    transport.get = vi.fn().mockResolvedValue(detailOf([...twelve, added]));
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf(twelve)}
        compact
        onOpenFull={() => undefined}
      />,
    );
    const field = await screen.findByLabelText(shoppingEn.batchShort);
    expect(
      screen.queryByRole("button", { name: shoppingEn.markBought("Bread") }),
    ).not.toBeInTheDocument();
    await user.type(field, "Bread{Enter}");
    expect(
      await screen.findByRole("button", {
        name: shoppingEn.markBought("Bread"),
      }),
    ).toBeInTheDocument();
    // The budget rows stay, and the link counts what is still left out: the other eight rows.
    expect(openRows()).toHaveLength(COMPACT_ROWS - 1 + 1);
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
