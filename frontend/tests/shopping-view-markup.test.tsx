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
import { readStylesheet } from "./helpers/stylesheet";

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

const css = readStylesheet("features/shopping-app/shopping.css");
const familyCss = readStylesheet("features/mcp-apps/ui/family.css");

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

describe("phone CSS contract for the purchase row (appended rules)", () => {
  it("the text column takes the free width and may shrink, so a long name wraps", () => {
    const rule = css.rule(".sidekick-shopping .shopping-item-text");
    expect(rule).toHaveProperty(["flex"], "1");
    expect(rule).toHaveProperty(["min-width"], "0");
    expect(rule).toHaveProperty(["overflow-wrap"], "anywhere");
  });

  it("the status is a muted meta line", () => {
    const rule = css.rule(".sidekick-shopping .shopping-status");
    expect(rule).toHaveProperty(["color"], "var(--work-muted)");
    expect(rule).toHaveProperty(["font-size"], "0.9rem");
  });

  it("the native checkbox is invisible and covers the whole row, so the row is its hit area", () => {
    // The shopping checkbox and the work step checkbox share one rule (shopping.css), so it is found by the whole list.
    const checkbox = css.rule(
      '.sidekick-shopping input[type="checkbox"], .sidekick-work .work-steps .work-step-check',
    );
    expect(checkbox).toHaveProperty(["position"], "absolute");
    expect(checkbox).toHaveProperty(["inset"], "0");
    expect(checkbox).toHaveProperty(["width"], "100%");
    expect(checkbox).toHaveProperty(["height"], "100%");
    expect(checkbox).toHaveProperty(["opacity"], "0");
    expect(css.rule(".sidekick-shopping .shopping-check")).toHaveProperty(
      ["position"],
      "relative",
    );
  });

  it("the status glyph is the visible 24 px ring in the leading column", () => {
    const glyph = css.rule(
      ".sidekick-shopping .shopping-check > .sk-status-glyph",
    );
    expect(glyph).toHaveProperty(["width"], "var(--sk-icon)");
    expect(glyph).toHaveProperty(["height"], "var(--sk-icon)");
  });

  it("the store view's ring is a stretched button, 48 wide with its ::after, ring on the first title line", () => {
    const ring = css.rule(".sidekick-shopping .shopping-ring");
    expect(ring).toHaveProperty(["width"], "var(--sk-lead-w)");
    expect(ring).toHaveProperty(["align-items"], "flex-start");
    expect(css.rule(".sidekick-shopping .shopping-store-line")).toHaveProperty(
      ["align-items"],
      "stretch",
    );
    expect(css.rule(".sidekick-shopping .shopping-ring::after")).toHaveProperty(
      ["inset"],
      "0 -2px",
    );
  });

  it("the store row is 48 px high, and buttons keep 44 px height", () => {
    expect(css.rule(".sidekick-shopping .shopping-store-row")).toHaveProperty(
      ["min-height"],
      "48px",
    );
    expect(familyCss.rule(".sk-btn")).toHaveProperty(
      ["min-height"],
      "var(--sk-tap)",
    );
  });
});
