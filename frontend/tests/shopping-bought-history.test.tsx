import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import { boughtOnText } from "@/features/shopping-app/shopping-view-parts/helpers";
import { elementWithText } from "./helpers/exact-text";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

const list: ShoppingList = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(n: number, over: Partial<ShoppingItem> = {}): ShoppingItem {
  return {
    id: `019f0000-0000-7000-8000-0000000000a${n}`,
    list_id: list.id,
    name: `Item ${n}`,
    quantity: "1",
    unit: null,
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

// Bought out of order on purpose: the fold lists the newest first, and an item with no recorded day last.
const bought = [
  item(1, { purchased: true, purchased_at: "2026-11-03T10:00:00Z" }),
  item(2, { purchased: true, purchased_at: "2026-11-05T10:00:00Z" }),
  item(3, { purchased: true, purchased_at: null }),
  item(4, { purchased: true, purchased_at: "2026-11-04T10:00:00Z" }),
];

function detail(items: ShoppingItem[]): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-11-13",
    next_offset: null,
    items,
  };
}

function transport(items: ShoppingItem[]): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail(items)),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
  };
}

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.shoppingBuyAgain;
  // The day labels read against today: a fixed clock keeps "3 Nov" a plain date.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-20T12:00:00Z"));
});
afterEach(() => {
  vi.useRealTimers();
});

describe("the day an item was bought", () => {
  it("reads as the app's other dates, in both languages", () => {
    const now = new Date("2026-11-20T12:00:00Z");
    expect(boughtOnText(bought[0]!, shoppingEn, now)).toBe("bought 3 Nov");
    expect(boughtOnText(bought[0]!, shoppingSv, now)).toBe("köpt 3 nov");
    expect(
      boughtOnText(
        item(5, { purchased: true, purchased_at: "2026-11-19T10:00:00Z" }),
        shoppingEn,
        now,
      ),
    ).toBe("bought yesterday");
  });

  it("leaves out the weekday inside a week: a list of what was bought has no use for it", () => {
    const now = new Date("2026-11-20T12:00:00Z");
    const threeDaysAgo = item(7, {
      purchased: true,
      purchased_at: "2026-11-17T10:00:00Z",
    });
    expect(boughtOnText(threeDaysAgo, shoppingEn, now)).toBe("bought 17 Nov");
    expect(boughtOnText(threeDaysAgo, shoppingSv, now)).toBe("köpt 17 nov");
  });

  it("is nothing for an open item or one with no recorded day", () => {
    const now = new Date("2026-11-20T12:00:00Z");
    expect(boughtOnText(bought[2]!, shoppingEn, now)).toBe("");
    expect(
      boughtOnText(
        item(6, { purchased_at: "2026-11-03T10:00:00Z" }),
        shoppingEn,
        now,
      ),
    ).toBe("");
  });
});

describe.each([
  { name: "English", labels: shoppingEn, day: "bought 5 Nov" },
  { name: "Swedish", labels: shoppingSv, day: "köpt 5 nov" },
] as { name: string; labels: ShoppingLabels; day: string }[])(
  "Köpta in the store view, $name",
  ({ labels, day }) => {
    async function openFold() {
      const user = userEvent.setup({ advanceTimers: () => undefined });
      render(
        <ShoppingView
          transport={transport(bought)}
          labels={labels}
          initial={detail(bought)}
          fullscreen
        />,
      );
      await user.click(elementWithText(labels.boughtCount(4), "button"));
      return screen.getAllByRole("listitem");
    }

    it("lists the newest first, each with its day, and an item without a day last", async () => {
      const rows = await openFold();
      expect(
        rows.map((row) => within(row).getByText(/Item \d/).textContent),
      ).toEqual(["Item 2", "Item 4", "Item 1", "Item 3"]);
      expect(within(rows[0]!).getByText(day)).toBeInTheDocument();
      expect(rows[3]!.textContent).not.toMatch(/bought|köpt/);
    });

    it("says once that the ring buys again", async () => {
      await openFold();
      expect(screen.getAllByText(labels.buyAgainTip)).toHaveLength(1);
    });
  },
);

it("stops saying that the ring buys again once an item has been bought again", async () => {
  const user = userEvent.setup({ advanceTimers: () => undefined });
  const reply = { ...bought[1]!, purchased: false, version: 2 };
  const source = transport(bought);
  vi.mocked(source.purchase).mockResolvedValue({ item: reply });
  const view = render(
    <ShoppingView
      transport={source}
      labels={shoppingEn}
      initial={detail(bought)}
      fullscreen
    />,
  );
  await user.click(elementWithText(shoppingEn.boughtCount(4), "button"));
  expect(screen.getByText(shoppingEn.buyAgainTip)).toBeInTheDocument();
  // Opening the fold taught nothing: the tip stands until a ring has bought an item again.
  await user.click(
    screen.getByRole("button", { name: shoppingEn.markOpen("Item 2") }),
  );
  expect(localStorage["sidekick.shoppingBuyAgainUsed"]).toBe("1");
  view.unmount();

  render(
    <ShoppingView
      transport={transport(bought)}
      labels={shoppingEn}
      initial={detail(bought)}
      fullscreen
    />,
  );
  await user.click(elementWithText(shoppingEn.boughtCount(4), "button"));
  expect(screen.queryByText(shoppingEn.buyAgainTip)).toBeNull();
});

it("says click, not tap, to buy again when the pointer is a mouse or trackpad", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: query === "(pointer: fine)" })),
  );
  try {
    const user = userEvent.setup({ advanceTimers: () => undefined });
    render(
      <ShoppingView
        transport={transport(bought)}
        labels={shoppingEn}
        initial={detail(bought)}
        fullscreen
      />,
    );
    await user.click(elementWithText(shoppingEn.boughtCount(4), "button"));
    expect(screen.getByText("Click the circle to buy again.")).toBeVisible();
    expect(screen.queryByText(shoppingEn.buyAgainTip)).toBeNull();
    expect(shoppingSv.buyAgainKeys).toBe("Klicka på ringen för att köpa igen.");
  } finally {
    vi.unstubAllGlobals();
  }
});

it("the list view shows the day too, but not the ring's tip", async () => {
  const user = userEvent.setup({ advanceTimers: () => undefined });
  render(
    <ShoppingView
      transport={transport(bought)}
      labels={shoppingEn}
      initial={detail(bought)}
    />,
  );
  await user.click(elementWithText(shoppingEn.boughtCount(4), "button"));
  expect(screen.getByText("bought 5 Nov")).toBeInTheDocument();
  expect(screen.queryByText(shoppingEn.buyAgainTip)).toBeNull();
});
