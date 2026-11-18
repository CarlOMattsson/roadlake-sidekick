import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ItemEditor } from "@/features/shopping-app/shopping-view-parts/item-editor";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type {
  ShoppingInput,
  ShoppingItem,
} from "@/features/shopping-app/transport";

const LIST_A = "019f0000-0000-7000-8000-000000000001";
const LIST_B = "019f0000-0000-7000-8000-000000000002";
const TWO_LISTS = [
  { id: LIST_A, name: "Groceries" },
  { id: LIST_B, name: "Hardware" },
];

function item(over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: "019f0000-0000-7000-8000-0000000000a0",
    list_id: LIST_A,
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

function renderEditor(
  options: {
    lists?: { id: string; name: string }[];
    stores?: string[];
    labels?: ShoppingLabels;
  } = {},
) {
  const onSave = vi.fn<(value: ShoppingInput) => void>();
  render(
    <ItemEditor
      item={item()}
      labels={options.labels ?? shoppingEn}
      busy={false}
      focusFirst={false}
      contacts={undefined}
      lists={options.lists ?? []}
      stores={options.stores ?? []}
      onCancel={vi.fn()}
      onSave={onSave}
    />,
  );
  return onSave;
}

describe("the item editor moves an item to another list", () => {
  it("offers a List select defaulting to the item's own list, and sends the other list with the fields", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor({ lists: TWO_LISTS });
    const select = screen.getByLabelText(shoppingEn.list);
    expect(select.tagName).toBe("SELECT");
    expect(select).toHaveValue(LIST_A);
    expect(
      screen.getByRole("option", { name: "Hardware" }),
    ).toBeInTheDocument();
    await user.selectOptions(select, LIST_B);
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]![0]).toMatchObject({
      list_id: LIST_B,
      name: "Milk",
      quantity: "2",
      unit: "l",
      store: "ICA MAXI 4",
    });
  });

  it("sends no list_id when the list was not changed", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor({ lists: TWO_LISTS });
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave.mock.calls[0]![0]).not.toHaveProperty("list_id");
  });

  it("sends no list_id when the list is changed and put back", async () => {
    const user = userEvent.setup();
    const onSave = renderEditor({ lists: TWO_LISTS });
    const select = screen.getByLabelText(shoppingEn.list);
    await user.selectOptions(select, LIST_B);
    await user.selectOptions(select, LIST_A);
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave.mock.calls[0]![0]).not.toHaveProperty("list_id");
  });

  it.each([
    ["no lists", []],
    ["a single list", [TWO_LISTS[0]!]],
  ])("shows no list select with %s", async (_name, lists) => {
    const user = userEvent.setup();
    const onSave = renderEditor({ lists });
    expect(screen.queryByLabelText(shoppingEn.list)).toBeNull();
    await user.click(screen.getByRole("button", { name: shoppingEn.save }));
    expect(onSave.mock.calls[0]![0]).not.toHaveProperty("list_id");
  });

  it("labels the select Lista in Swedish", () => {
    renderEditor({ lists: TWO_LISTS, labels: shoppingSv });
    expect(screen.getByLabelText("Lista").tagName).toBe("SELECT");
  });
});

describe("the item editor suggests the shops of the list", () => {
  it("gives the store field a datalist with the stores as options", () => {
    renderEditor({ stores: ["ICA MAXI 4", "Willys"] });
    const field = screen.getByLabelText(shoppingEn.store);
    const listId = field.getAttribute("list");
    expect(listId).toBeTruthy();
    const datalist = document.getElementById(listId!);
    expect(datalist?.tagName).toBe("DATALIST");
    expect(
      Array.from(datalist!.querySelectorAll("option")).map(
        (option) => option.value,
      ),
    ).toEqual(["ICA MAXI 4", "Willys"]);
  });

  it("has an empty datalist when no store is known", () => {
    renderEditor();
    const listId = screen.getByLabelText(shoppingEn.store).getAttribute("list");
    expect(document.getElementById(listId!)?.children).toHaveLength(0);
  });
});
