import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// "Edit list" in fullscreen renames the open list with update_shopping_list. It shows no create form.

const weekly: ShoppingList = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Veckohandel",
  version: 3,
  archived: false,
  open_count: 0,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const other: ShoppingList = {
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

function adapter(): ShoppingTransport {
  return {
    lists: vi
      .fn()
      .mockResolvedValue({ lists: [weekly, other], next_offset: null }),
    get: vi.fn().mockResolvedValue(detailOf(weekly)),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
  };
}

describe("fullscreen Edit list renames the open list", () => {
  it("shows the list's name in a rename field and no create form or list picker", async () => {
    const user = userEvent.setup();
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detailOf(weekly)}
        fullscreen
      />,
    );
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: shoppingEn.editList }));
    expect(screen.getByLabelText(shoppingEn.listName)).toHaveValue(weekly.name);
    expect(
      screen.queryByRole("button", { name: shoppingEn.create }),
    ).not.toBeInTheDocument();
    expect(screen.queryByLabelText(shoppingEn.select)).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: shoppingEn.save })).toBeEnabled();
  });

  it("saves the new name with update_shopping_list against the version that was read", async () => {
    const user = userEvent.setup();
    const transport = adapter();
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detailOf(weekly)}
        fullscreen
      />,
    );
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: shoppingEn.editList }));
    const field = screen.getByLabelText(shoppingEn.listName);
    await user.clear(field);
    await user.type(field, "Veckohandel stor{Enter}");
    await waitFor(() => expect(transport.rename).toHaveBeenCalledTimes(1));
    const [list, name, archived, key] = vi.mocked(transport.rename).mock
      .calls[0]!;
    expect(list).toMatchObject({ id: weekly.id, version: 3 });
    expect(name).toBe("Veckohandel stor");
    expect(archived).toBe(false);
    expect(typeof key).toBe("string");
    // The edit closes once the rename is saved.
    await waitFor(() =>
      expect(
        screen.queryByLabelText(shoppingEn.listName),
      ).not.toBeInTheDocument(),
    );
  });
});
