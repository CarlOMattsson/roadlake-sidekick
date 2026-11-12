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
import { elementWithText } from "./helpers/exact-text";

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
    store: "ICA MAXI 4",
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [
    item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" }),
    item({
      id: "019f0000-0000-7000-8000-0000000000a3",
      name: "Eggs",
      purchased: true,
    }),
  ],
};

function adapter(over: Partial<ShoppingTransport> = {}): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn().mockResolvedValue({}),
    update: vi.fn(),
    purchase: vi.fn().mockResolvedValue({}),
    ...over,
  };
}

function storeView(
  transport: ShoppingTransport,
  value: ShoppingDetail = detail,
) {
  return (
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={value}
      fullscreen
    />
  );
}

async function waitLoaded() {
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
}

/**
 * What opens the create field: in fullscreen the round ink + in the Back row; in a card the
 * "+ Add item" row. Both are named "Add item" and show aria-expanded.
 */
function addRow() {
  return screen.getByRole("button", { name: shoppingEn.addItem });
}

function quickField() {
  return screen.getByRole("textbox", { name: shoppingEn.addItem });
}

/** A click on "+ Add item" opens the create field in its place; the field takes the focus at once. */
async function openField(user: ReturnType<typeof userEvent.setup>) {
  await user.click(addRow());
  return quickField();
}

it("store view has no standing field: + Add item starts closed and opens the field with focus", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  // No mode switch and no standing field: the field appears only after the click.
  expect(
    screen.queryByRole("button", { name: shoppingEn.editList }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.listName)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  // Fullscreen: the + stands in the Back row (before ⋯); there is no "+ Add item" row in the list.
  expect(document.querySelector(".shopping-add-trigger")).toBeNull();
  expect(document.querySelector(".shopping-add-row")).toBeNull();
  expect(addRow()).toBeEnabled();
  expect(transport.add).not.toHaveBeenCalled();

  await user.click(addRow());
  const field = quickField();
  expect(field).toHaveFocus();
  expect(field).toHaveAttribute("placeholder", shoppingEn.addItemPlaceholder);
  expect(transport.add).not.toHaveBeenCalled();
});

it("fullscreen has the + in the Back row before ⋯ and no + Add item row; the field it opens comes after the progress line and before the first shop", async () => {
  const user = userEvent.setup();
  const { container } = render(storeView(adapter()));
  await waitLoaded();
  const plus = addRow();
  expect(plus).toHaveClass("shopping-add", "sk-iconbtn", "sk-iconbtn--primary");
  expect(plus).toHaveAttribute("aria-expanded", "false");
  expect(plus.closest(".sk-back-header__actions")).not.toBeNull();
  const more = screen.getByRole("button", { name: shoppingEn.moreActions });
  expect(
    plus.compareDocumentPosition(more) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(container.querySelector(".shopping-add-row")).toBeNull();

  await user.click(plus);
  expect(plus).toHaveAttribute("aria-expanded", "true");
  const row = quickField().closest(".shopping-create");
  if (!row) throw new Error("no create field");
  const firstShop = screen
    .getByRole("button", { name: /^Mark Milk as/ })
    .closest("section.shopping-group");
  // The field stands first in the list: under the progress line and before the first shop's group, never inside one.
  expect(row.previousElementSibling).toHaveClass("shopping-progress");
  expect(row.nextElementSibling).toBe(firstShop);
  expect(row.closest("section.shopping-group")).toBeNull();
  const purchased = elementWithText(shoppingEn.boughtCount(1), "button");
  expect(
    row.compareDocumentPosition(purchased) & Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
});

it("an empty field shows × Close; with text the square becomes the Add button", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  const close = screen.getByRole("button", { name: shoppingEn.close });
  expect(close).toHaveClass("sk-createfield__btn");
  expect(
    screen.queryByRole("button", { name: shoppingEn.addItemButton }),
  ).not.toBeInTheDocument();

  await user.type(field, "Bröd");
  const add = screen.getByRole("button", { name: shoppingEn.addItemButton });
  expect(add).toHaveClass("sk-createfield__btn--add");
  expect(
    screen.queryByRole("button", { name: shoppingEn.close }),
  ).not.toBeInTheDocument();
  expect(transport.add).not.toHaveBeenCalled();
});

it("the Add button sends one add write with the typed name, empties the field and keeps it open with focus", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Bröd");
  await user.click(
    screen.getByRole("button", { name: shoppingEn.addItemButton }),
  );
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  const [id, names, key, options] = vi.mocked(transport.add).mock.calls[0]!;
  expect(id).toBe(list.id);
  expect(names).toEqual(["Bröd"]);
  expect(key).toBeTruthy();
  expect(options).toEqual({ mergeDuplicates: true });
  // The field empties once the write has answered, stays open with the focus, and × is back in place of +.
  await waitFor(() => expect(field).toHaveValue(""));
  expect(field).toHaveFocus();
  expect(
    screen.getByRole("button", { name: shoppingEn.close }),
  ).toBeInTheDocument();
});

it("Enter in the field sends the item, empties it and keeps the focus", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Ägg{Enter}");
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  expect(vi.mocked(transport.add).mock.calls[0]![1]).toEqual(["Ägg"]);
  await waitFor(() => expect(field).toHaveValue(""));
  expect(field).toHaveFocus();
});

it("a quick add says where the item went under the field, keeps the focus, and Esc clears it", async () => {
  const added = item({
    id: "019f0000-0000-7000-8000-0000000000a9",
    name: "Oats",
    store: "ICA",
  });
  const transport = adapter({
    add: vi.fn().mockResolvedValue({ items: [{ item: added, merged: false }] }),
  });
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "oats{Enter}");
  const note = await screen.findByText("Added: Oats · ICA");
  expect(note).toHaveAttribute("aria-live", "polite");
  expect(field).toHaveFocus();
  await user.keyboard("{Escape}");
  await user.click(addRow());
  expect(screen.queryByText("Added: Oats · ICA")).not.toBeInTheDocument();
});

it("a failed quick add hides the earlier receipt", async () => {
  const transport = adapter({
    add: vi
      .fn()
      .mockResolvedValueOnce({
        items: [{ item: item({ store: null }), merged: true }],
      })
      .mockRejectedValueOnce(new Error("network down")),
  });
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "milk{Enter}");
  expect(await screen.findByText("Added: Milk")).toBeInTheDocument();
  await user.type(field, "Smör{Enter}");
  await screen.findByRole("alert");
  expect(screen.queryByText("Added: Milk")).not.toBeInTheDocument();
});

it("Enter with an empty or blank field sends nothing", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "   {Enter}");
  expect(transport.add).not.toHaveBeenCalled();
});

it("Esc closes the field and gives the focus back to + Add item", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  await openField(user);
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  expect(addRow()).toHaveFocus();
  expect(transport.add).not.toHaveBeenCalled();
});

it("× closes the empty field and gives the focus back to + Add item", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  await openField(user);
  await user.click(screen.getByRole("button", { name: shoppingEn.close }));
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  expect(addRow()).toHaveFocus();
});

it("a failed add keeps the text under the field with 'Couldn’t save', and Add sends the same name with the same key", async () => {
  const transport = adapter({
    add: vi
      .fn()
      .mockRejectedValueOnce(new Error("network down"))
      .mockResolvedValue({}),
  });
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Smör{Enter}");
  const alert = await screen.findByRole("alert");
  expect(alert).toHaveTextContent(shoppingEn.saveFailed);
  // The text stays in the field, and the list-level failure notice does not show for this write.
  expect(field).toHaveValue("Smör");
  expect(screen.queryByText(shoppingEn.failed)).not.toBeInTheDocument();
  await user.click(
    screen.getByRole("button", { name: shoppingEn.addItemButton }),
  );
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(2));
  const [first, second] = vi.mocked(transport.add).mock.calls;
  expect(first![1]).toEqual(["Smör"]);
  expect(second![1]).toEqual(["Smör"]);
  expect(second![2]).toBe(first![2]);
  await waitFor(() => expect(field).toHaveValue(""));
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});

it("a quick add in a shop view puts the item in that shop and merges a same-named open item", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen
      store="ICA MAXI 4"
    />,
  );
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Bröd{Enter}");
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  const [id, names, , options] = vi.mocked(transport.add).mock.calls[0]!;
  expect(id).toBe(list.id);
  expect(names).toEqual(["Bröd"]);
  expect(options).toEqual({ store: "ICA MAXI 4", mergeDuplicates: true });
});

it("a quick add without a shop filter sends no store, but still merges", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Bröd{Enter}");
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  const options = vi.mocked(transport.add).mock.calls[0]![3];
  expect(options?.store).toBeUndefined();
  expect(options?.mergeDuplicates).toBe(true);
});

it("an empty list shows + Add item, keeps the field closed until a click, and says what the list is for", async () => {
  const empty: ShoppingDetail = { ...detail, items: [] };
  const transport = adapter({ get: vi.fn().mockResolvedValue(empty) });
  const user = userEvent.setup();
  render(storeView(transport, empty));
  await waitLoaded();
  expect(addRow()).toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  // The empty state says what the list is for (uc-3), with its own "+ Add an item".
  expect(screen.getByText(shoppingEn.empty)).toBeInTheDocument();
  expect(screen.getByText(shoppingEn.emptyHint)).toBeInTheDocument();
  await user.click(addRow());
  expect(quickField()).toHaveFocus();
});

it("archived list in store view has neither + Add item nor a quick add field", async () => {
  const archivedList = { ...list, archived: true };
  const archived: ShoppingDetail = { ...detail, shopping_list: archivedList };
  // The reload reads the list again, so the adapter must return the archived list too.
  const transport = adapter({
    lists: vi
      .fn()
      .mockResolvedValue({ lists: [archivedList], next_offset: null }),
    get: vi.fn().mockResolvedValue(archived),
  });
  render(storeView(transport, archived));
  await waitLoaded();
  expect(
    screen.queryByRole("button", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
});

it("the quick add labels are Swedish in the Swedish set", () => {
  expect(shoppingSv.addItem).toBe("Lägg till vara");
  expect(shoppingSv.addItemButton).toBe("Lägg till");
  expect(shoppingSv.close).toBe("Stäng");
});

it("a store card (not fullscreen) keeps the + Add item row in the list and has no + in a Back row", async () => {
  const { container } = render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingEn}
      initial={detail}
      store="Coop"
    />,
  );
  await waitLoaded();
  const row = container.querySelector(".shopping-add-row");
  expect(row).not.toBeNull();
  expect(row).toHaveTextContent(shoppingEn.addItem);
  expect(container.querySelector(".shopping-add")).toBeNull();
  expect(container.querySelector(".sk-iconbtn--primary")).toBeNull();
});

it("the fullscreen + is named in both languages (locale parity)", async () => {
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingSv}
      initial={detail}
      fullscreen
    />,
  );
  await waitLoaded();
  const plus = screen.getByRole("button", { name: shoppingSv.addItem });
  expect(plus).toHaveClass("sk-iconbtn--primary");
  expect(shoppingEn.addItem).not.toBe(shoppingSv.addItem);
});

it("commas in the field add several items in one write, trimmed and without empty names", async () => {
  const transport = adapter({
    add: vi.fn().mockResolvedValue({
      items: [
        { item: item({ id: "a1", name: "Glödlampor", store: "ICA" }) },
        { item: item({ id: "a2", name: "Mjölk", store: "ICA" }) },
      ],
    }),
  });
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "glödlampor, mjölk ,{Enter}");
  await waitFor(() => expect(transport.add).toHaveBeenCalledTimes(1));
  expect(vi.mocked(transport.add).mock.calls[0]![1]).toEqual([
    "glödlampor",
    "mjölk",
  ]);
  expect(
    await screen.findByText("Added: Glödlampor, Mjölk · ICA"),
  ).toBeVisible();
  await waitFor(() => expect(field).toHaveValue(""));
});

it("the placeholder is the same in both languages' examples: no quantity is read from the text", () => {
  expect(shoppingEn.addItemPlaceholder).toBe("New item, e.g. milk, eggs");
  expect(shoppingSv.addItemPlaceholder).toBe("Ny vara, t.ex. mjölk, ägg");
});

it("Esc closes the field also when the focus has moved to a button outside it", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  await openField(user);
  screen.getByRole("button", { name: shoppingEn.moreActions }).focus();
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  expect(addRow()).toHaveFocus();
});

it("Esc closes the field after an add, and gives the focus back to +", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(storeView(transport));
  await waitLoaded();
  const field = await openField(user);
  await user.type(field, "Ägg{Enter}");
  await waitFor(() => expect(field).toHaveValue(""));
  await user.keyboard("{Escape}");
  expect(
    screen.queryByRole("textbox", { name: shoppingEn.addItem }),
  ).not.toBeInTheDocument();
  expect(addRow()).toHaveFocus();
});
