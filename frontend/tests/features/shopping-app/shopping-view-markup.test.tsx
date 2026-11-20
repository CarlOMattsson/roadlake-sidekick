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
  it("an open row is a ring and a row button side by side, with no status line", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    const ring = await screen.findByRole("button", {
      name: shoppingEn.markBought("Milk"),
    });
    await waitFor(() => expect(ring).toBeEnabled());
    expect(ring).toHaveClass("shopping-ring");
    const line = ring.parentElement;
    expect(line).toHaveClass("shopping-store-line");
    // The row's own button is the ring's sibling, never nested in it, and there is no "To buy" status line.
    const rowButton = line?.querySelector(":scope > .shopping-store-row");
    expect(rowButton).toBeInTheDocument();
    expect(rowButton).not.toContainElement(ring);
    expect(line?.closest("li")?.querySelector(".shopping-status")).toBeNull();
    // No checkbox and no Edit button remain: the row itself opens the change form.
    expect(screen.queryByRole("checkbox")).toBeNull();
    expect(
      screen.queryByRole("button", { name: shoppingEn.editNamed("Milk") }),
    ).toBeNull();
  });

  it("the name and the amount keep their own text, so the row reads as 'name' and 'quantity unit'", async () => {
    render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: shoppingEn.markBought("Milk") }),
      ).toBeEnabled(),
    );
    expect(screen.getByText("Milk")).toHaveClass("shopping-store-name");
    expect(screen.getByText("2 l")).toHaveClass("shopping-store-qty");
  });

  it("a bought item has no status line; its ring reads 'not bought'", async () => {
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
    const ring = await screen.findByRole("button", {
      name: shoppingEn.markOpen("Milk"),
    });
    const row = ring.closest("li");
    expect(row).toHaveClass("shopping-store-item");
    expect(row?.querySelector(".shopping-status")).toBeNull();
    expect(row?.querySelector(".shopping-store-name")).toHaveTextContent(
      "Milk",
    );
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
    expect(await screen.findByText("Mjölk")).toBeInTheDocument();
    expect(screen.getByText("2 l")).toHaveClass("shopping-store-qty");
    expect(screen.getByText("12 st")).toHaveClass("shopping-store-qty");
    expect(screen.getByText("Bröd")).toBeInTheDocument();
    expect(screen.getByText("1,5 l")).toHaveClass("shopping-store-qty");
    // No amount for 1 with no unit: the name stands alone.
    const bread = screen.getByText("Bröd").closest("li");
    expect(bread?.querySelector(".shopping-store-qty")).toBeNull();
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
      expect(
        screen.getByRole("button", { name: shoppingEn.markBought("Milk") }),
      ).toBeEnabled(),
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
