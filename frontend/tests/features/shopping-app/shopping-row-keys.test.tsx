import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type {
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { findReceiptUndo, receiptText } from "@tests/helpers/receipt-bar";

// The store view in fullscreen: the rows are one Tab stop, the arrow keys (and j, k, Home, End) move over them across
// the store groups and the bought fold, ← and → over a row's own controls, x buys, Delete deletes. After Save, Delete
// and Move the focus stays in the list. The row menu is a popover with a mouse. Simulated events in jsdom, not a real
// browser or host.

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const weekend = {
  ...list,
  id: "019f0000-0000-7000-8000-000000000002",
  name: "Weekend",
};

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: "019f0000-0000-7000-8000-0000000000a0",
    list_id: list.id,
    name: "Milk",
    quantity: "2",
    unit: null,
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
    version: 3,
    ...over,
  };
}

const milk = item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" });
const bread = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Bread",
});
const soap = item({
  id: "019f0000-0000-7000-8000-0000000000a3",
  name: "Soap",
  store: null,
});
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a4",
  name: "Eggs",
  store: null,
  purchased: true,
  purchased_at: "2026-10-23T12:00:00Z",
});

/** A list that answers as a server does: a write changes what the next read returns. */
function server(start: ShoppingItem[] = [milk, bread, soap, eggs]) {
  let items = start;
  const transport: ShoppingTransport = {
    lists: vi
      .fn()
      .mockResolvedValue({ lists: [list, weekend], next_offset: null }),
    get: vi.fn(() =>
      Promise.resolve({
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items,
      }),
    ),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn<ShoppingTransport["update"]>((row, input) => {
      const next = {
        ...row,
        name: input.name ?? row.name,
        store: input.store === undefined ? row.store : input.store,
        list_id: input.list_id ?? row.list_id,
        version: row.version + 1,
      };
      items = items
        .map((entry) => (entry.id === row.id ? next : entry))
        .filter((entry) => entry.list_id === list.id);
      return Promise.resolve({ item: next });
    }),
    purchase: vi.fn().mockResolvedValue({}),
    trashItem: vi.fn<NonNullable<ShoppingTransport["trashItem"]>>((id) => {
      items = items.filter((entry) => entry.id !== id);
      return Promise.resolve({ version: 8 });
    }),
    restoreItem: vi.fn().mockResolvedValue({}),
  };
  return { transport, initial: () => items };
}

async function mount(
  fake = server(),
  options: { fullscreen?: boolean; labels?: ShoppingLabels } = {},
) {
  const labels = options.labels ?? shoppingEn;
  render(
    <ShoppingView
      transport={fake.transport}
      labels={labels}
      initial={{
        shopping_list: list,
        evaluated_on: "2026-10-24",
        next_offset: null,
        items: fake.initial(),
      }}
      fullscreen={options.fullscreen ?? true}
    />,
  );
  await waitFor(() =>
    expect(screen.queryByText(labels.loading)).not.toBeInTheDocument(),
  );
  return fake.transport;
}

/** The row's main button (its name). */
const row = (name: string) =>
  screen
    .getByText(name, { selector: ".shopping-store-name" })
    .closest("button")!;

/** The fold of the bought items (one: Eggs). */
const boughtFold = () =>
  document.querySelector<HTMLElement>(".shopping-purchased .sk-fold")!;

/** The names of the rows in the order they are drawn. */
const order = () =>
  [...document.querySelectorAll(".shopping-store-name")].map(
    (node) => node.textContent,
  );

/** The tab stops of the rows: every control of a row's line with a tabindex of 0 or none. */
const stops = () =>
  [...document.querySelectorAll<HTMLElement>(".shopping-store-line button")]
    .filter((button) => button.tabIndex === 0)
    .map(
      (button) =>
        button.closest("li")?.querySelector(".shopping-store-name")
          ?.textContent,
    );

afterEach(() => {
  delete document.documentElement.dataset.hostPointer;
});

describe("the rows are one Tab stop", () => {
  it("gives only the first row a tab stop, and Tab passes the rest of the list", async () => {
    const user = userEvent.setup();
    await mount();
    expect(order()).toEqual(["Milk", "Bread", "Soap"]);
    expect(stops()).toEqual(["Milk"]);
    for (const button of document.querySelectorAll<HTMLElement>(
      ".shopping-store-line button",
    )) {
      if (button !== row("Milk")) expect(button.tabIndex).toBe(-1);
    }
    row("Milk").focus();
    await user.tab();
    expect(document.activeElement?.closest(".shopping-store-line")).toBeNull();
  });

  it("moves the stop to the row that has the focus", async () => {
    const user = userEvent.setup();
    await mount();
    row("Milk").focus();
    await user.keyboard("{ArrowDown}");
    expect(row("Bread")).toHaveFocus();
    expect(stops()).toEqual(["Bread"]);
  });

  it("leaves the Tab order of the inline card as it was", async () => {
    await mount(server(), { fullscreen: false });
    const buttons = [
      ...document.querySelectorAll<HTMLElement>(".shopping-store-line button"),
    ];
    expect(buttons.length).toBeGreaterThan(3);
    for (const button of buttons)
      expect(button).not.toHaveAttribute("tabindex");
  });
});

describe("the arrow keys move over the rows", () => {
  it("↓ ↑ j k Home and End go over the groups and stop at the ends", async () => {
    const user = userEvent.setup();
    await mount();
    row("Milk").focus();
    await user.keyboard("{ArrowDown}");
    expect(row("Bread")).toHaveFocus();
    await user.keyboard("j");
    expect(row("Soap")).toHaveFocus();
    await user.keyboard("{ArrowDown}");
    expect(row("Soap")).toHaveFocus();
    await user.keyboard("k");
    expect(row("Bread")).toHaveFocus();
    await user.keyboard("{ArrowUp}");
    expect(row("Milk")).toHaveFocus();
    await user.keyboard("{End}");
    expect(row("Soap")).toHaveFocus();
    await user.keyboard("{Home}");
    expect(row("Milk")).toHaveFocus();
  });

  it("goes on into the bought fold when it is open", async () => {
    const user = userEvent.setup();
    await mount();
    await user.click(boughtFold());
    row("Soap").focus();
    await user.keyboard("{ArrowDown}");
    expect(row("Eggs")).toHaveFocus();
    expect(stops()).toEqual(["Eggs"]);
  });

  it("moves from any control of a row to the next row's name", async () => {
    const user = userEvent.setup();
    await mount();
    screen.getByRole("button", { name: shoppingEn.markBought("Milk") }).focus();
    await user.keyboard("{ArrowDown}");
    expect(row("Bread")).toHaveFocus();
  });

  it("← and → move over the row's own controls", async () => {
    const user = userEvent.setup();
    await mount();
    row("Milk").focus();
    const named = (name: string) => screen.getByRole("button", { name: name });
    await user.keyboard("{ArrowLeft}");
    expect(named(shoppingEn.markBought("Milk"))).toHaveFocus();
    await user.keyboard("{ArrowLeft}");
    expect(named(shoppingEn.markBought("Milk"))).toHaveFocus();
    await user.keyboard("{ArrowRight}{ArrowRight}");
    expect(named(shoppingEn.decreaseQuantity("Milk"))).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(named(shoppingEn.increaseQuantity("Milk"))).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(named(shoppingEn.rowMenu("Milk"))).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(named(shoppingEn.rowMenu("Milk"))).toHaveFocus();
    // The controls keep their stop out of the Tab order: only the name is a stop.
    expect(stops()).toEqual(["Milk"]);
  });

  it("does nothing in a field", async () => {
    const user = userEvent.setup();
    await mount();
    await user.click(row("Milk"));
    const name = screen.getByLabelText(shoppingEn.name);
    await user.type(name, "jk");
    expect(name).toHaveFocus();
    expect(name).toHaveValue("Milkjk");
  });

  it("Enter on the name still opens the change form", async () => {
    const user = userEvent.setup();
    await mount();
    row("Bread").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText(shoppingEn.name)).toHaveValue("Bread");
  });
});

describe("x and Delete act on the row that has the focus", () => {
  it("x buys the row as the ring does", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    row("Bread").focus();
    await user.keyboard("x");
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.purchase).mock.calls[0]![0]).toMatchObject({
      id: bread.id,
    });
  });

  it("Delete moves the row to the trash, with Ångra, and the focus goes to the next row", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    row("Milk").focus();
    await user.keyboard("{Delete}");
    await waitFor(() =>
      expect(transport.trashItem).toHaveBeenCalledWith(
        milk.id,
        milk.version,
        expect.any(String),
      ),
    );
    await waitFor(() => expect(receiptText()).toBe("Deleted: Milk"));
    await findReceiptUndo("Undo");
    await waitFor(() => expect(order()).toEqual(["Bread", "Soap"]));
    expect(row("Bread")).toHaveFocus();
  });

  it("Backspace on the last row sends the focus to the one before", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    row("Soap").focus();
    await user.keyboard("{Backspace}");
    await waitFor(() => expect(transport.trashItem).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(order()).toEqual(["Milk", "Bread"]));
    expect(row("Bread")).toHaveFocus();
  });

  it("says Ta bort in Swedish", async () => {
    const user = userEvent.setup();
    await mount(server(), { labels: shoppingSv });
    row("Milk").focus();
    await user.keyboard("{Delete}");
    await waitFor(() => expect(receiptText()).toBe("Borttagen: Milk"));
  });

  it("leaves a bought row alone", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    await user.click(boughtFold());
    row("Eggs").focus();
    await user.keyboard("{Delete}");
    expect(transport.trashItem).not.toHaveBeenCalled();
  });
});

describe("Enter saves the change form", () => {
  async function openForm(user: ReturnType<typeof userEvent.setup>) {
    await user.click(row("Milk"));
    return screen.getByLabelText(shoppingEn.name);
  }

  it("saves from a one-line field and Escape cancels, with the focus back on the row", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    const name = await openForm(user);
    await user.clear(name);
    await user.type(name, "Oat milk{Enter}");
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toMatchObject({
      name: "Oat milk",
    });
  });

  it("Escape cancels and gives the focus back to the row", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    // Opened with the keyboard, the form has the focus on its first field.
    row("Milk").focus();
    await user.keyboard("{Enter}");
    expect(screen.getByLabelText(shoppingEn.name)).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(transport.update).not.toHaveBeenCalled();
    expect(screen.queryByLabelText(shoppingEn.name)).toBeNull();
    expect(row("Milk")).toHaveFocus();
  });

  it("does not save from the note, where Enter is a new line", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    await openForm(user);
    await user.click(screen.getByRole("button", { name: /^More fields/ }));
    await user.type(screen.getByLabelText(shoppingEn.note), "a{Enter}b");
    expect(transport.update).not.toHaveBeenCalled();
  });

  it("leaves Enter to the shop's suggestions while the text only matches other shops", async () => {
    const user = userEvent.setup();
    const transport = await mount();
    await openForm(user);
    const store = screen.getByLabelText(shoppingEn.store);
    await user.clear(store);
    // "IC" matches the suggestion ICA, which differs from it: Enter belongs to the list.
    await user.type(store, "IC{Enter}");
    expect(transport.update).not.toHaveBeenCalled();
    await user.type(store, "A{Enter}");
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
  });
});

describe("the focus stays in the list", () => {
  it("returns to the row after Save, also when the row has moved to another store group", async () => {
    const user = userEvent.setup();
    const fake = server();
    await mount(fake);
    await user.click(row("Milk"));
    const store = screen.getByLabelText(shoppingEn.store);
    await user.clear(store);
    await user.type(store, "Willys");
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    await waitFor(() => expect(fake.transport.update).toHaveBeenCalled());
    await waitFor(() =>
      expect(screen.queryByLabelText(shoppingEn.name)).toBeNull(),
    );
    await waitFor(() => expect(row("Milk")).toHaveFocus());
    // Milk now stands under its new shop's heading, and is the row that has the focus.
    expect(
      row("Milk").closest(".shopping-group")?.querySelector("h3"),
    ).toHaveTextContent("Willys");
  });

  it("goes to the next row after Delete in the change form", async () => {
    const user = userEvent.setup();
    await mount();
    await user.click(row("Bread"));
    await user.click(screen.getByRole("button", { name: "Delete Bread" }));
    await waitFor(() => expect(order()).toEqual(["Milk", "Soap"]));
    expect(row("Soap")).toHaveFocus();
  });

  it("goes to the next row after Delete and after a move from the row menu", async () => {
    const user = userEvent.setup();
    const fake = server();
    await mount(fake);
    await user.click(
      screen.getByRole("button", { name: shoppingEn.rowMenu("Milk") }),
    );
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moveToList("Weekend") }),
    );
    await waitFor(() => expect(order()).toEqual(["Bread", "Soap"]));
    expect(row("Bread")).toHaveFocus();
    await user.click(
      screen.getByRole("button", { name: shoppingEn.rowMenu("Bread") }),
    );
    await user.click(screen.getByRole("button", { name: "Delete" }));
    await waitFor(() => expect(order()).toEqual(["Soap"]));
    expect(row("Soap")).toHaveFocus();
  });

  it("does not take the focus from where the user has moved it", async () => {
    const user = userEvent.setup();
    await mount();
    await user.click(row("Milk"));
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    screen.getByRole("button", { name: shoppingEn.addItem }).focus();
    await waitFor(() =>
      expect(screen.queryByLabelText(shoppingEn.name)).toBeNull(),
    );
    expect(
      screen.getByRole("button", { name: shoppingEn.addItem }),
    ).toHaveFocus();
  });
});

describe("the row menu is a popover with a mouse", () => {
  const trigger = (name = "Milk") =>
    screen.getByRole("button", { name: shoppingEn.rowMenu(name) });

  it("opens at ⋯, names the item and has no ×", async () => {
    document.documentElement.dataset.hostPointer = "fine";
    const user = userEvent.setup();
    await mount();
    await user.click(trigger());
    const menu = document.querySelector<HTMLElement>("[data-menu]")!;
    expect(menu).toHaveAttribute("data-menu", "popover");
    expect(menu).toHaveClass("shopping-row-popover");
    expect(trigger()).toHaveAttribute("aria-controls", menu.id);
    expect(within(menu).getByText("Milk")).toBeInTheDocument();
    // The first entry has the focus.
    expect(
      within(menu).getByRole("button", {
        name: shoppingEn.moveToList("Weekend"),
      }),
    ).toHaveFocus();
  });

  it("Escape closes it and gives the focus back to ⋯", async () => {
    document.documentElement.dataset.hostPointer = "fine";
    const user = userEvent.setup();
    await mount();
    await user.click(trigger());
    await user.keyboard("{Escape}");
    expect(document.querySelector("[data-menu]")).toBeNull();
    expect(trigger()).toHaveFocus();
    expect(trigger()).toHaveAttribute("aria-expanded", "false");
  });

  it("Tab and a press outside close it without a choice", async () => {
    document.documentElement.dataset.hostPointer = "fine";
    const user = userEvent.setup();
    const transport = await mount();
    await user.click(trigger());
    await user.keyboard("{Tab}");
    expect(document.querySelector("[data-menu]")).toBeNull();
    await user.click(trigger());
    await user.click(row("Soap"));
    expect(document.querySelector("[data-menu]")).toBeNull();
    expect(transport.update).not.toHaveBeenCalled();
    expect(transport.trashItem).not.toHaveBeenCalled();
  });

  it("is the panel in the flow on a phone, with its ×", async () => {
    const user = userEvent.setup();
    await mount();
    await user.click(trigger());
    expect(document.querySelector("[data-menu]")).toHaveAttribute(
      "data-menu",
      "panel",
    );
    await user.click(
      screen.getByRole("button", { name: shoppingEn.closeMenu }),
    );
    expect(trigger()).toHaveFocus();
  });
});
