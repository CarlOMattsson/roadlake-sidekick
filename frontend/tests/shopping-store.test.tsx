import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
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
      id: "019f0000-0000-7000-8000-0000000000a2",
      name: "Shelf",
      store: "IKEA",
    }),
    item({
      id: "019f0000-0000-7000-8000-0000000000a3",
      name: "Eggs",
      purchased: true,
    }),
  ],
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
    purchase: vi.fn().mockResolvedValue({}),
  };
}

it("fullscreen shows the store view: one tap on a row marks the item bought", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  // The forms are not shown directly: the list is the view, and "Edit list" opens the forms.
  expect(screen.queryByLabelText(shoppingEn.listName)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.batch)).not.toBeInTheDocument();
  expect(screen.getByText(shoppingEn.boughtOf(1, 3))).toBeInTheDocument();
  // The ring is the button that marks the item bought; a tap on the name opens its change form instead.
  await user.click(screen.getByRole("button", { name: "Mark Milk as bought" }));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  const [bought, key] = vi.mocked(transport.purchase).mock.calls[0]!;
  expect(bought).toMatchObject({ id: detail.items[0]!.id, purchased: false });
  expect(key).toBeTruthy();
});

it("Edit list reveals the list and item forms", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(
    screen.getByRole("button", { name: shoppingEn.moreActions }),
  );
  const toggle = screen.getByRole("button", { name: shoppingEn.editList });
  expect(toggle).toHaveAttribute("aria-expanded", "false");
  await user.click(toggle);
  expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
  expect(screen.getByLabelText(shoppingEn.batch)).toBeInTheDocument();
});

it("the ⋯ menu ends with Control, which asks the host for the Control room's memory view", async () => {
  const transport = adapter();
  const user = userEvent.setup();
  const onNavigate = vi.fn();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen
      onNavigate={onNavigate}
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  const more = screen.getByRole("button", { name: shoppingEn.moreActions });
  // The ⋯ is an icon, not a character.
  expect(more.querySelector("svg")).not.toBeNull();
  expect(more).not.toHaveTextContent("⋯");
  await user.click(more);
  const entries = within(
    document.querySelector<HTMLElement>(".shopping-more-menu")!,
  ).getAllByRole("button");
  expect(entries.map((entry) => entry.textContent)).toEqual([
    shoppingEn.editList,
    "Memory and control",
  ]);
  await user.click(entries[1]!);
  expect(onNavigate).toHaveBeenCalledWith({ room: "control", view: "memory" });
});

it("the ⋯ menu has no Control entry when the view cannot navigate", async () => {
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(
    screen.getByRole("button", { name: shoppingEn.moreActions }),
  );
  expect(
    screen.queryByRole("button", { name: "Memory and control" }),
  ).not.toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: shoppingEn.editList }),
  ).toBeInTheDocument();
});

it("inline without fullscreen keeps the full list view with its forms", async () => {
  const transport = adapter();
  render(
    <ShoppingView transport={transport} labels={shoppingEn} initial={detail} />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: shoppingEn.editList }),
  ).not.toBeInTheDocument();
});
