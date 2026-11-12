import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import { ShoppingRoom } from "@/features/shopping-app/room";
import type {
  ShoppingDetail,
  ShoppingItem,
} from "@/features/shopping-app/transport";

// A late result for the list the view has written must not take a confirmed row back to an older version.

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const milkId = "019f0000-0000-7000-8000-0000000000a1";

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: milkId,
    list_id: list.id,
    name: "Milk",
    quantity: "1",
    unit: "st",
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

const v1: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [item({})],
};

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterAll(() => {
  document.head.innerHTML = "";
});

it("keeps a confirmed newer row when a result with an older version of it arrives", async () => {
  const user = userEvent.setup();
  const call = vi.fn(async (name: string) => {
    if (name === "set_shopping_item_purchased")
      return { item: item({ purchased: true, version: 2 }) };
    if (name === "list_shopping_lists")
      return { lists: [list], next_offset: null };
    return new Promise(() => undefined);
  });
  const transport = {
    call: call as never,
    requestDisplayMode: vi.fn() as never,
    updateModelContext: vi.fn() as never,
  };
  const { rerender } = render(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={v1}
      resultId={1}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  );
  await waitFor(() =>
    expect(screen.getByRole("button", { name: /Undo/ })).toBeInTheDocument(),
  );
  // A delayed result still carries Milk at v1.
  act(() =>
    rerender(
      <ShoppingRoom
        mode="full"
        transport={transport}
        initial={{ ...v1, items: [item({})] }}
        resultId={2}
      />,
    ),
  );
  // The bought row stands under the folded "Bought (1)": open it to reach the row.
  await user.click(await screen.findByRole("button", { name: /^Bought/ }));
  expect(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  ).toHaveAccessibleName(/as not bought/);
});

it("still replaces the rows of a different list", async () => {
  const other: ShoppingDetail = {
    ...v1,
    shopping_list: { ...list, id: "other", name: "Party" },
    items: [item({ id: "z", list_id: "other", name: "Cake" })],
  };
  const transport = {
    call: vi.fn(() => new Promise(() => undefined)) as never,
    requestDisplayMode: vi.fn() as never,
    updateModelContext: vi.fn() as never,
  };
  const { rerender } = render(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={v1}
      resultId={1}
    />,
  );
  expect(await screen.findByText("Milk")).toBeInTheDocument();
  rerender(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={other}
      resultId={2}
    />,
  );
  expect(await screen.findByText("Cake")).toBeInTheDocument();
});

it("shows a purchase reply that arrives after a newer result mounted the view again (N5)", async () => {
  const user = userEvent.setup();
  let answer!: () => void;
  const call = vi.fn((name: string) => {
    if (name === "set_shopping_item_purchased")
      return new Promise((resolve) => {
        answer = () => resolve({ item: item({ purchased: true, version: 2 }) });
      });
    if (name === "list_shopping_lists")
      return Promise.resolve({ lists: [list], next_offset: null });
    return new Promise(() => undefined);
  });
  const transport = {
    call: call as never,
    requestDisplayMode: vi.fn() as never,
    updateModelContext: vi.fn() as never,
  };
  const { rerender } = render(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={v1}
      resultId={1}
    />,
  );
  await user.click(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  );
  // A result arrives while the write runs: the view is mounted again, from v1.
  rerender(
    <ShoppingRoom
      mode="full"
      transport={transport}
      initial={{ ...v1, items: [item({})] }}
      resultId={2}
    />,
  );
  expect(
    await screen.findByRole("button", { name: /^Mark Milk as/ }),
  ).toHaveAccessibleName(/as bought/);
  act(() => answer());
  // The bought row stands under the folded "Bought (1)".
  await user.click(await screen.findByRole("button", { name: /^Bought/ }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: /^Mark Milk as/ }),
    ).toHaveAccessibleName(/as not bought/),
  );
});
