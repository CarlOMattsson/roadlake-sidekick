import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingList,
} from "@/features/shopping-app/transport";

// The first visit reads list_shopping_lists once, also when a single list opens at once.
// Choosing a list afterwards reads that list only.

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

function detailOf(list: ShoppingList): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items: [],
  };
}

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

afterAll(() => {
  document.head.innerHTML = "";
});

/** The transport mock: the list tools answer; `lists` is the page the lists read returns. */
function makeTransport(lists: ShoppingList[]) {
  const call = vi.fn(async (name: string, args?: { list_id?: string }) => {
    if (name === "list_shopping_lists") return { lists, next_offset: null };
    if (name === "get_shopping_list") {
      const list = lists.find((entry) => entry.id === args?.list_id);
      return detailOf(list ?? lists[0]!);
    }
    return new Promise(() => undefined);
  });
  const transport: RoomTransport = {
    call: call as unknown as RoomTransport["call"],
    requestDisplayMode:
      vi.fn() as unknown as RoomTransport["requestDisplayMode"],
    updateModelContext:
      vi.fn() as unknown as RoomTransport["updateModelContext"],
  };
  return { call, transport };
}

function countOf(
  call: ReturnType<typeof makeTransport>["call"],
  tool: string,
): number {
  return call.mock.calls.filter(([name]) => name === tool).length;
}

describe("a first visit reads the lists once", () => {
  it("a single list that opens at once is read from one lists read, not two", async () => {
    const { call, transport } = makeTransport([weekly]);
    render(<ShoppingRoom mode="full" transport={transport} />);
    expect(
      await screen.findByRole("heading", { name: weekly.name }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(countOf(call, "list_shopping_lists")).toBe(1);
    expect(countOf(call, "get_shopping_list")).toBe(1);
  });

  it("tapping a row reads that list, not the lists again", async () => {
    const user = userEvent.setup();
    const { call, transport } = makeTransport([weekly, ikea]);
    render(<ShoppingRoom mode="full" transport={transport} />);
    await user.click(
      await screen.findByRole("button", { name: new RegExp(`^${ikea.name}`) }),
    );
    expect(
      await screen.findByRole("heading", { name: ikea.name }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(countOf(call, "list_shopping_lists")).toBe(1);
    expect(countOf(call, "get_shopping_list")).toBe(1);
    // The way back is the shared BackHeader: its name is "Back to" plus the list label, in this English app.
    expect(
      screen.getByRole("button", { name: `Back to ${shoppingEn.backToLists}` }),
    ).toBeEnabled();
  });
});
