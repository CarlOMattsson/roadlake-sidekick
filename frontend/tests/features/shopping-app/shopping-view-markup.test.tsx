import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
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
  open_count: 0,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

const milk: ShoppingItem = {
  id: "019f0000-0000-7000-8000-0000000000a1",
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
  store: null,
  target_date: null,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
  version: 1,
};

const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk],
};

function adapter(over: Partial<ShoppingTransport> = {}): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
    ...over,
  };
}

describe("purchase row markup (phone)", () => {
  it("the status is part of the checkbox label, under the name, not a sibling of the Edit button", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    const checkbox = await screen.findByRole("checkbox", { name: /Milk/ });
    await waitFor(() => expect(checkbox).toBeEnabled());
    const row = checkbox.closest("label");
    expect(row).toHaveClass("shopping-check");
    expect(row).toHaveTextContent(shoppingEn.wanted);
    const status = screen.getByText(shoppingEn.wanted);
    expect(status).toHaveClass("shopping-status");
    expect(row?.contains(status)).toBe(true);
    const toolbar = row?.parentElement;
    expect(toolbar).toHaveClass("shopping-toolbar");
    expect(toolbar?.querySelector(":scope > button")).toHaveTextContent(
      shoppingEn.edit,
    );
    expect(toolbar?.querySelector(":scope > span")).toBeNull();
  });

  it("the name line keeps its own text, so the item reads as 'name · quantity unit'", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /Milk/ })).toBeEnabled(),
    );
    expect(screen.getByText("Milk · 2 l")).toBeInTheDocument();
  });

  it("a bought item has no status line; its checkbox is ticked", async () => {
    const bought = { ...milk, purchased: true };
    const boughtDetail = { ...detail, items: [bought] };
    render(
      <ShoppingView
        transport={adapter({
          get: vi.fn().mockResolvedValue(boughtDetail),
        })}
        labels={shoppingEn}
        initial={boughtDetail}
      />,
    );
    // A bought item stands under the folded "Bought (1)": open it.
    fireEvent.click(await screen.findByRole("button", { name: /^Bought/ }));
    const name = await screen.findByText("Milk · 2 l");
    const row = name.closest("label");
    expect(row).toHaveClass("shopping-check");
    expect(row?.querySelector(".shopping-status")).toBeNull();
    expect(row?.querySelector('input[type="checkbox"]')).toBeChecked();
  });
});

describe("list quantities read like the card", () => {
  it("a decimal amount shows without trailing zeros, with the Swedish decimal comma; no unit and 1 is the name only", async () => {
    const amounts: ShoppingItem[] = [
      {
        ...milk,
        id: "019f0000-0000-7000-8000-0000000000b1",
        name: "Mjölk",
        quantity: "2.000",
        unit: "l",
      },
      {
        ...milk,
        id: "019f0000-0000-7000-8000-0000000000b2",
        name: "Ägg",
        quantity: "12.000",
        unit: "st",
      },
      {
        ...milk,
        id: "019f0000-0000-7000-8000-0000000000b3",
        name: "Bröd",
        quantity: "1.000",
        unit: null,
      },
      {
        ...milk,
        id: "019f0000-0000-7000-8000-0000000000b4",
        name: "Yoghurt",
        quantity: "1.500",
        unit: "l",
      },
    ];
    const amountDetail = { ...detail, items: amounts };
    render(
      <ShoppingView
        transport={adapter({
          get: vi.fn().mockResolvedValue(amountDetail),
        })}
        labels={shoppingSv}
        initial={amountDetail}
      />,
    );
    expect(await screen.findByText("Mjölk · 2 l")).toBeInTheDocument();
    expect(screen.getByText("Ägg · 12 st")).toBeInTheDocument();
    expect(screen.getByText("Bröd")).toBeInTheDocument();
    expect(screen.getByText("Yoghurt · 1,5 l")).toBeInTheDocument();
    expect(screen.queryByText(/1\.000|2\.000|12\.000/)).toBeNull();
  });
});

describe("list pager shows only when there is more than one page of lists", () => {
  it("a single page of lists has no previous or next button", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    await waitFor(() =>
      expect(screen.getByRole("checkbox", { name: /Milk/ })).toBeEnabled(),
    );
    expect(
      screen.queryByRole("button", { name: shoppingEn.previous }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: shoppingEn.next })).toBeNull();
  });

  it("a second page of lists shows Next; Previous is shown disabled on page 1 and enabled on page 2", async () => {
    const user = userEvent.setup();
    const lists = vi.fn((offset: number) =>
      Promise.resolve(
        offset === 0
          ? { lists: [list], next_offset: 50 }
          : { lists: [list], next_offset: null },
      ),
    );
    render(<ShoppingView transport={adapter({ lists })} labels={shoppingEn} />);
    const next = await screen.findByRole("button", { name: shoppingEn.next });
    await waitFor(() => expect(next).toBeEnabled());
    const previous = screen.getByRole("button", { name: shoppingEn.previous });
    expect(previous).toBeDisabled();
    await user.click(next);
    await waitFor(() => expect(previous).toBeEnabled());
    expect(lists).toHaveBeenLastCalledWith(50);
  });
});
