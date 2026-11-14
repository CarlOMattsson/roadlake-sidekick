import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingList,
} from "@/features/shopping-app/transport";

// A list chosen in an inline card (after list_shopping_lists) shows only the list, folded, not the
// old full edit view with its create form, list picker and edit forms.

const weekly: ShoppingList = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 1,
  archived: false,
  open_count: 0,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const ikea: ShoppingList = {
  ...weekly,
  id: "019f0000-0000-7000-8000-000000000002",
  name: "IKEA someday",
};

const detail: ShoppingDetail = {
  shopping_list: ikea,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [],
};

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

afterAll(() => {
  document.head.innerHTML = "";
});

function makeTransport() {
  const call = vi.fn(async (name: string) => {
    if (name === "list_shopping_lists")
      return { lists: [weekly, ikea], next_offset: null };
    if (name === "get_shopping_list") return detail;
    return new Promise(() => undefined);
  });
  const transport: RoomTransport = {
    call: call as unknown as RoomTransport["call"],
    requestDisplayMode: vi
      .fn()
      .mockResolvedValue(
        "fullscreen",
      ) as unknown as RoomTransport["requestDisplayMode"],
    updateModelContext:
      vi.fn() as unknown as RoomTransport["updateModelContext"],
  };
  return transport;
}

it("tapping a list in an inline card shows the folded list, not the edit view", async () => {
  const user = userEvent.setup();
  const { container } = render(
    <ShoppingRoom
      initial={{ lists: [weekly, ikea], next_offset: null }}
      resultId={1}
      mode="inline"
      fullscreenAvailable
      transport={makeTransport()}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: /^IKEA someday/ }),
  );
  expect(
    await screen.findByRole("heading", { name: "IKEA someday" }),
  ).toBeInTheDocument();
  const card = container.querySelector("section.sidekick-shopping");
  expect(card).toHaveClass("shopping-folded");
  expect(
    screen.queryByRole("button", { name: shoppingEn.create }),
  ).not.toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.select)).not.toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.listName)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: shoppingEn.editList }),
  ).not.toBeInTheDocument();
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
});
