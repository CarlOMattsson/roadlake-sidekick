import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import type {
  ShoppingDetail,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

/** Desktop spec 3.4: in a wide frame (the shell offers its head row) the lists stand beside the chosen list. */

function listOf(n: number, name: string, updated: string) {
  return {
    id: `019f0000-0000-7000-8000-${String(n).padStart(12, "0")}`,
    name,
    version: 1,
    archived: false,
    open_count: 5,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: updated,
  } as ShoppingList;
}

const food = listOf(1, "Food", "2026-10-24T12:00:00Z");
const office = listOf(2, "Office", "2026-10-25T09:00:00Z");

function detailOf(list: ShoppingList): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-25",
    next_offset: null,
    items: [
      {
        id: `${list.id.slice(0, -1)}9`,
        list_id: list.id,
        name: "Milk",
        quantity: "1",
        unit: null,
        purchased: false,
        version: 1,
      } as unknown as ShoppingDetail["items"][number],
    ],
  };
}

function adapter() {
  return {
    lists: vi.fn().mockResolvedValue({
      lists: [food, office],
      next_offset: null,
    }),
    get: vi.fn((id: string) =>
      Promise.resolve(detailOf(id === food.id ? food : office)),
    ),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
  } as ShoppingTransport;
}

function renderWide(transport: ShoppingTransport, slot: HTMLElement | null) {
  return render(
    <RoomSurfaceContext.Provider
      value={{ active: true, framed: true, headSlot: slot }}
    >
      <ShoppingView transport={transport} labels={shoppingEn} fullscreen />
    </RoomSurfaceContext.Provider>,
  );
}

describe("Shopping in a wide frame", () => {
  it("opens the list changed last beside the lists, drawn chosen, with no way back", async () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    const transport = adapter();
    renderWide(transport, slot);
    expect(
      await screen.findByRole("heading", { level: 2, name: "Office" }),
    ).toBeInTheDocument();
    expect(vi.mocked(transport.get).mock.calls[0]?.[0]).toBe(office.id);
    const lists = screen.getByRole("list", { name: shoppingEn.lists });
    const chosen = within(lists).getByRole("button", { name: /^Office/ });
    expect(chosen).toHaveAttribute("aria-current", "true");
    expect(
      within(lists).getByRole("button", { name: /^Food/ }),
    ).not.toHaveAttribute("aria-current");
    // The chosen list's count comes from its own read: one open item.
    expect(chosen).toHaveTextContent(shoppingEn.listLeft(1));
    expect(
      screen.queryByRole("button", {
        name: new RegExp(shoppingEn.backToLists),
      }),
    ).not.toBeInTheDocument();
    // "New list" is the lists' last row; + and ⋯ are the room head's, in the shell's row.
    expect(
      screen.getByRole("button", { name: shoppingEn.newList }),
    ).toBeInTheDocument();
    expect(
      within(slot).getByRole("button", { name: shoppingEn.addItem }),
    ).toBeInTheDocument();
    slot.remove();
  });

  it("swaps the list beside the lists and reads the lists again", async () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    const transport = adapter();
    renderWide(transport, slot);
    await screen.findByRole("heading", { level: 2, name: "Office" });
    const reads = vi.mocked(transport.lists).mock.calls.length;
    await userEvent.click(screen.getByRole("button", { name: /^Food/ }));
    expect(
      await screen.findByRole("heading", { level: 2, name: "Food" }),
    ).toBeInTheDocument();
    await waitFor(() =>
      expect(vi.mocked(transport.lists).mock.calls.length).toBeGreaterThan(
        reads,
      ),
    );
    slot.remove();
  });

  it("keeps the phone's picker and way back without the shell's head row", async () => {
    renderWide(adapter(), null);
    await userEvent.click(await screen.findByRole("button", { name: /^Food/ }));
    expect(
      await screen.findByRole("button", {
        name: new RegExp(shoppingEn.backToLists),
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("list", { name: shoppingEn.lists }),
    ).not.toBeInTheDocument();
  });
});
