import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { findReceiptUndo, receiptText } from "@tests/helpers/receipt-bar";

// The row's ⋯ menu: it names its item, closes with its own button (focus back on ⋯), and ends in Delete, which is
// the whole menu when there is no other list to move to. Simulated events in jsdom, not a real touch device.

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

const milk: ShoppingItem = {
  id: "019f0000-0000-7000-8000-0000000000a1",
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
  version: 3,
};
const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk],
};
const without: ShoppingDetail = { ...detail, items: [] };

function adapter(
  lists: (typeof list)[],
  over: Partial<ShoppingTransport> = {},
): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists, next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
    trashItem: vi.fn().mockResolvedValue({ version: 8 }),
    restoreItem: vi.fn().mockResolvedValue({}),
    ...over,
  };
}

async function mount(
  transport: ShoppingTransport,
  labels: ShoppingLabels = shoppingEn,
) {
  render(
    <ShoppingView
      transport={transport}
      labels={labels}
      initial={detail}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByText(labels.loading)).not.toBeInTheDocument(),
  );
}

/** The ⋯ of Milk's row. */
function more(labels: ShoppingLabels = shoppingEn) {
  return screen.getByRole("button", { name: labels.rowMenu("Milk") });
}

/** The open row menu, found by the name it carries. */
function menu(labels: ShoppingLabels = shoppingEn) {
  const close = screen.getByRole("button", { name: labels.closeMenu });
  return close.closest(".shopping-row-menu") as HTMLElement;
}

describe.each([
  { language: "English", labels: shoppingEn, del: "Delete" },
  { language: "Swedish", labels: shoppingSv, del: "Ta bort" },
])("the row menu in $language", ({ labels, del }) => {
  it("names its item and offers a move target and Delete", async () => {
    const user = userEvent.setup();
    await mount(adapter([list, weekend]), labels);
    expect(more(labels)).toHaveAttribute("aria-expanded", "false");
    await user.click(more(labels));
    expect(more(labels)).toHaveAttribute("aria-expanded", "true");
    const panel = menu(labels);
    // The head names the item the menu belongs to.
    expect(within(panel).getByText("Milk")).toHaveClass(
      "shopping-row-menu-name",
    );
    expect(
      within(panel).getByRole("button", {
        name: labels.moveToList("Weekend"),
      }),
    ).toBeVisible();
    const trash = within(panel).getByRole("button", { name: del });
    expect(trash).toHaveClass("sk-menu-item--danger");
    // Delete stands last.
    expect(panel.lastElementChild).toBe(trash);
  });

  it("closes with its close button and gives the focus back to ⋯", async () => {
    const user = userEvent.setup();
    await mount(adapter([list, weekend]), labels);
    await user.click(more(labels));
    await user.click(screen.getByRole("button", { name: labels.closeMenu }));
    expect(
      screen.queryByRole("button", { name: labels.closeMenu }),
    ).not.toBeInTheDocument();
    expect(more(labels)).toHaveAttribute("aria-expanded", "false");
    expect(more(labels)).toHaveFocus();
  });

  it("Delete moves the item to the trash at its version and closes the menu", async () => {
    const user = userEvent.setup();
    const transport = adapter([list, weekend], {
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await mount(transport, labels);
    await user.click(more(labels));
    await user.click(within(menu(labels)).getByRole("button", { name: del }));
    expect(transport.trashItem).toHaveBeenCalledTimes(1);
    expect(transport.trashItem).toHaveBeenCalledWith(
      milk.id,
      milk.version,
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
    // The menu is shut at once, and the receipt bar says it with Ångra.
    expect(
      screen.queryByRole("button", { name: labels.closeMenu }),
    ).not.toBeInTheDocument();
    expect(await findReceiptUndo(labels.undoTrash)).toBeVisible();
    expect(receiptText()).toBe(labels.itemTrashed("Milk"));
  });
});

describe("the row menu when Delete is all it has", () => {
  it("shows ⋯ for an item when there is no other list to move it to", async () => {
    const user = userEvent.setup();
    const transport = adapter([list]);
    await mount(transport);
    await user.click(more());
    const panel = menu();
    // No move entries: the name, the close button and Delete.
    expect(
      within(panel).queryByRole("button", { name: /^Move to/ }),
    ).not.toBeInTheDocument();
    expect(
      within(panel).getByRole("button", { name: shoppingEn.deleteItem }),
    ).toBeVisible();
    await user.click(
      within(panel).getByRole("button", { name: shoppingEn.deleteItem }),
    );
    expect(transport.trashItem).toHaveBeenCalledTimes(1);
  });

  it("Escape closes the menu and puts the focus back on ⋯", async () => {
    const user = userEvent.setup();
    await mount(adapter([list]));
    await user.click(more());
    expect(menu()).toBeVisible();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: shoppingEn.closeMenu }),
    ).not.toBeInTheDocument();
    expect(more()).toHaveFocus();
  });

  it("has no ⋯ when there is neither another list nor a trash", async () => {
    await mount(
      adapter([list], { trashItem: undefined, restoreItem: undefined }),
    );
    expect(
      screen.queryByRole("button", { name: shoppingEn.rowMenu("Milk") }),
    ).not.toBeInTheDocument();
  });
});
