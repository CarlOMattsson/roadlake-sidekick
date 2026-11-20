import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

function listOf(n: number, name: string, openCount: number) {
  return {
    id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    name,
    version: 1,
    archived: false,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    open_count: openCount,
  };
}

function itemOf(
  list: ShoppingList,
  n: number,
  name: string,
  over: Partial<ShoppingItem> = {},
): ShoppingItem {
  return {
    id: `019f0000-0000-7000-8000-0000000000a${n}`,
    list_id: list.id,
    name,
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

/** An answer that arrives a moment later, as one over the host bridge does. */
function later<T>(value: () => T): Promise<T> {
  return new Promise((resolve) => setTimeout(() => resolve(value()), 15));
}

/** A server whose lists change as the view writes: the overview must follow what the server then says. */
function server() {
  const state = {
    lists: [listOf(1, "Matinköp", 18), listOf(2, "Kontoret", 4)],
    items: new Map<string, ShoppingItem[]>(),
  };
  const detailOf = (id: string): ShoppingDetail => ({
    shopping_list: state.lists.find((entry) => entry.id === id)!,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: state.items.get(id) ?? [],
  });
  const transport: ShoppingTransport = {
    lists: vi.fn(() =>
      later(() => ({
        lists: state.lists.map((entry) => ({ ...entry })),
        next_offset: null,
      })),
    ),
    get: vi.fn((id: string) => later(() => detailOf(id))),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn((name: string) =>
      later(() => {
        const made = listOf(9, name, 1);
        state.lists.push(made);
        state.items.set(made.id, [itemOf(made, 9, "Gurka")]);
        return { shopping_list: made };
      }),
    ),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn((item: ShoppingItem) => {
      const [first, second] = state.lists as [ShoppingList, ShoppingList];
      first.open_count = 14;
      second.open_count = 5;
      return Promise.resolve({
        item: { ...item, purchased: true, version: item.version + 1 },
      });
    }),
  };
  return { state, transport };
}

function view(transport: ShoppingTransport) {
  return render(
    <ShoppingView transport={transport} labels={shoppingEn} fullscreen />,
  );
}

async function openList(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  const row = await screen.findByRole("button", {
    name: new RegExp(`^${name}`),
  });
  await waitFor(() => expect(row).toBeEnabled());
  await user.click(row);
}

async function backToLists(user: ReturnType<typeof userEvent.setup>) {
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(
    screen.getByRole("button", { name: new RegExp(shoppingEn.backToLists) }),
  );
}

describe("the lists overview follows what this view wrote", () => {
  it("shows the counts the server has after ticking items off and coming back to Lists", async () => {
    const { state, transport } = server();
    const [first] = state.lists as [ShoppingList];
    state.items.set(first.id, [itemOf(first, 1, "Gurka")]);
    const user = userEvent.setup();
    view(transport);
    await openList(user, "Matinköp");
    await user.click(
      await screen.findByRole("button", {
        name: shoppingEn.markBought("Gurka"),
      }),
    );
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
    await backToLists(user);

    const lists = await screen.findByRole("list", { name: shoppingEn.lists });
    await waitFor(() =>
      expect(
        within(lists).getByRole("button", { name: /^Matinköp/ }),
      ).toHaveTextContent(shoppingEn.listLeft(14)),
    );
    expect(
      within(lists).getByRole("button", { name: /^Kontoret/ }),
    ).toHaveTextContent(shoppingEn.listLeft(5));
  });

  it("offers a list made in this view in the overview and in the item editor's list choice", async () => {
    const { transport } = server();
    const user = userEvent.setup();
    view(transport);
    await screen.findByRole("button", { name: /^Matinköp/ });
    await user.click(screen.getByRole("button", { name: shoppingEn.newList }));
    await user.type(
      screen.getByRole("textbox", { name: shoppingEn.newList }),
      "Fest lördag{Enter}",
    );
    // The new list is opened; its own name is among the lists the editor can move an item between.
    await user.click(await screen.findByRole("button", { name: /^Gurka/ }));
    const choice = await screen.findByLabelText(shoppingEn.list);
    await waitFor(() =>
      expect(
        within(choice).getByRole("option", { name: "Fest lördag" }),
      ).toBeInTheDocument(),
    );
    await backToLists(user);
    expect(
      await screen.findByRole("button", { name: /^Fest lördag/ }),
    ).toBeInTheDocument();
  });
});
