import { render, screen, waitFor } from "@testing-library/react";
import { afterAll, beforeAll, expect, it, vi } from "vitest";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
} from "@/features/shopping-app/transport";

// An inline list card mounted again after a write in the full view (refreshKey above 0)
// reads its list by id itself. The result it was given is kept on screen until the fresh list arrives, and the
// list picker never shows in its place.

const list: ShoppingList = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 1,
  archived: false,
  open_count: 0,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const lampa: ShoppingItem = {
  id: "019f0000-0000-7000-8000-000000000010",
  list_id: list.id,
  name: "Lampa",
  quantity: "1",
  unit: null,
  purchased: false,
  purchased_at: null,
  offer_status: "none",
  version: 1,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

/** The result the card was opened with: Lampa is still open. */
const stale: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [lampa],
};

/** The list read after the owner ticked Lampa off in the full view. */
const fresh: ShoppingDetail = {
  ...stale,
  items: [{ ...lampa, purchased: true, purchased_at: "2026-10-24T12:05:00Z" }],
};

beforeAll(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

afterAll(() => {
  document.head.innerHTML = "";
});

function makeTransport(getList: (id: string) => Promise<ShoppingDetail>) {
  const call = vi.fn(async (name: string, args?: { list_id?: string }) => {
    if (name === "get_shopping_list") return getList(args?.list_id ?? "");
    if (name === "list_shopping_lists")
      return { lists: [list], next_offset: null };
    return new Promise(() => undefined);
  });
  const transport: RoomTransport = {
    call: call as unknown as RoomTransport["call"],
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn(),
  };
  return { transport, call };
}

it("an inline card after a write in the full view reads its list by id and shows the fresh state", async () => {
  let answer: (value: ShoppingDetail) => void = () => undefined;
  const pending = new Promise<ShoppingDetail>((resolve) => {
    answer = resolve;
  });
  const { transport, call } = makeTransport(() => pending);
  render(
    <ShoppingRoom
      initial={stale}
      resultId={1}
      mode="inline"
      fullscreenAvailable
      refreshKey={1}
      transport={transport}
    />,
  );
  // The read is in flight: the card keeps what it showed, and no list picker appears.
  expect(
    call.mock.calls.some(
      ([name, args]) =>
        name === "get_shopping_list" && args?.list_id === list.id,
    ),
  ).toBe(true);
  expect(screen.getByText(shoppingEn.boughtOf(0, 1))).toBeInTheDocument();
  expect(screen.queryByLabelText(shoppingEn.select)).not.toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: shoppingEn.create }),
  ).not.toBeInTheDocument();
  // The fresh list arrives: the card shows that Lampa is bought, not the old count.
  answer(fresh);
  expect(await screen.findByText(shoppingEn.allBought)).toBeInTheDocument();
  await waitFor(() =>
    expect(
      screen.queryByText(shoppingEn.boughtOf(0, 1)),
    ).not.toBeInTheDocument(),
  );
});

it("a first inline card with its result does not read the list again", async () => {
  const { transport, call } = makeTransport(() => Promise.resolve(stale));
  render(
    <ShoppingRoom
      initial={stale}
      resultId={1}
      mode="inline"
      fullscreenAvailable
      refreshKey={0}
      transport={transport}
    />,
  );
  expect(
    await screen.findByText(shoppingEn.boughtOf(0, 1)),
  ).toBeInTheDocument();
  expect(
    call.mock.calls.filter(([name]) => name === "get_shopping_list"),
  ).toHaveLength(0);
});
