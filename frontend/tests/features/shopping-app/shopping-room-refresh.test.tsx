import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
} from "@/features/shopping-app/transport";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
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

// One module-level object: the room sees the same `initial` on every render, so no new result is delivered.
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

beforeAll(() => {
  // The room reads its language from the app meta when it renders: English labels here.
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

afterAll(() => {
  document.head.innerHTML = "";
});

/** The transport mock: the list tools answer, the write tools never run in these tests. */
function makeTransport() {
  const call = vi.fn(async (name: string) => {
    if (name === "list_shopping_lists")
      return { lists: [list], next_offset: null };
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
  return { call, transport };
}

/** Room props for a fullscreen room that already holds its list from the opening result. */
function roomProps(transport: RoomTransport, refreshKey: number): RoomProps {
  return { initial: detail, resultId: 1, mode: "full", transport, refreshKey };
}

/** How many times the room has read a list detail. */
function detailReads(call: ReturnType<typeof makeTransport>["call"]): number {
  return call.mock.calls.filter(([name]) => name === "get_shopping_list")
    .length;
}

/** Waits until the first read has finished, so the test types into a settled view. */
async function settle(call: ReturnType<typeof makeTransport>["call"]) {
  // The opening result carries the list, so the first visit makes no read of it.
  expect(detailReads(call)).toBe(0);
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
}

it("reads again in place on a changed refreshKey and keeps the typed names text and the open editor", async () => {
  const user = userEvent.setup();
  const { call, transport } = makeTransport();
  const { rerender } = render(<ShoppingRoom {...roomProps(transport, 0)} />);
  await settle(call);
  // The batch field is the full one in fullscreen behind "Edit list".
  await user.click(
    screen.getByRole("button", { name: shoppingEn.moreActions }),
  );
  await user.click(screen.getByRole("button", { name: shoppingEn.editList }));
  const names = screen.getByLabelText(shoppingEn.batch);
  await user.type(names, "Mjölk, ägg");
  expect(detailReads(call)).toBe(0);

  rerender(<ShoppingRoom {...roomProps(transport, 1)} />);
  await waitFor(() => expect(detailReads(call)).toBe(1));
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
  // (a) the typed text is still there, (b) the list was read again, (c) the room was not remounted.
  expect(screen.getByLabelText(shoppingEn.batch)).toBe(names);
  expect(names).toHaveValue("Mjölk, ägg");
  expect(screen.getByLabelText(shoppingEn.listName)).toBeInTheDocument();
});

it("keeps the quick-add text when the room reads again", async () => {
  const user = userEvent.setup();
  const { call, transport } = makeTransport();
  const { rerender } = render(<ShoppingRoom {...roomProps(transport, 0)} />);
  await settle(call);
  // Fullscreen without the edit panel is the store view: its quick-add field opens behind "+ Add item" in the list.
  await user.click(screen.getByRole("button", { name: shoppingEn.addItem }));
  const quick = screen.getByRole("textbox", { name: shoppingEn.addItem });
  await user.type(quick, "Bröd");

  rerender(<ShoppingRoom {...roomProps(transport, 1)} />);
  await waitFor(() => expect(detailReads(call)).toBe(1));
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
  expect(screen.getByRole("textbox", { name: shoppingEn.addItem })).toBe(quick);
  expect(quick).toHaveValue("Bröd");
});

it("does not read again for the refreshKey the room mounted with", async () => {
  const { call, transport } = makeTransport();
  const { rerender } = render(<ShoppingRoom {...roomProps(transport, 7)} />);
  await settle(call);
  expect(detailReads(call)).toBe(0);
  rerender(<ShoppingRoom {...roomProps(transport, 7)} />);
  expect(detailReads(call)).toBe(0);
});
