import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// While a chosen list is read, the old form does not flash; a calm loading line shows instead.

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

describe("reading a chosen list in fullscreen", () => {
  it("shows the loading line and no create form, select or hint until the list has answered", async () => {
    const user = userEvent.setup();
    let answer: (value: ShoppingDetail) => void = () => undefined;
    const transport: ShoppingTransport = {
      lists: vi
        .fn()
        .mockResolvedValue({ lists: [weekly, ikea], next_offset: null }),
      get: vi.fn(
        () =>
          new Promise<ShoppingDetail>((resolve) => {
            answer = resolve;
          }),
      ),
      contacts: vi.fn().mockResolvedValue({ contacts: [] }),
      create: vi.fn(),
      rename: vi.fn(),
      add: vi.fn(),
      update: vi.fn(),
      purchase: vi.fn(),
    };
    render(
      <ShoppingView transport={transport} labels={shoppingEn} fullscreen />,
    );
    await user.click(
      await screen.findByRole("button", { name: new RegExp(`^${ikea.name}`) }),
    );
    // The read is pending: the loading line shows, and the old form does not.
    expect(screen.getByRole("status")).toHaveTextContent(shoppingEn.loading);
    expect(
      screen.queryByRole("button", { name: shoppingEn.create }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByLabelText(shoppingEn.listName),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(shoppingEn.select)).not.toBeInTheDocument();
    expect(screen.queryByText(shoppingEn.hint)).not.toBeInTheDocument();

    act(() => {
      answer(detailOf(ikea));
    });
    expect(
      await screen.findByRole("heading", { name: ikea.name }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("status")).not.toBeInTheDocument();
  });
});
