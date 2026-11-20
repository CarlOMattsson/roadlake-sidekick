import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { findReceiptUndo, receiptSlot } from "@tests/helpers/receipt-bar";

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
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
    purchase: vi.fn().mockResolvedValue({
      item: { ...milk, purchased: true, version: 2 },
    }),
    ...over,
  };
}

describe("loading", () => {
  it("the loading line is shown while the list is read", async () => {
    const { container } = render(
      <ShoppingView
        transport={adapter({
          lists: vi.fn(() => new Promise<never>(() => undefined)),
        })}
        labels={shoppingEn}
      />,
    );
    await waitFor(() =>
      expect(container.querySelector(".shopping-loading")).not.toBeNull(),
    );
    expect(container.querySelector(".shopping-loading")).toHaveTextContent(
      shoppingEn.loading,
    );
  });
});

describe("a bought row holds its place and its Ångra is in the receipt bar", () => {
  it("the row keeps its room and says 'Bought' with no button of its own; the bar's Ångra is a compact quiet button, last in the view", async () => {
    const user = userEvent.setup();
    const { container } = render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingEn}
        initial={detail}
        fullscreen
      />,
    );
    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /^Mark Milk as/ }),
      ).toBeEnabled(),
    );
    const openRow = screen.getByText("Milk").closest("li")!;
    await user.click(screen.getByRole("button", { name: /^Mark Milk as/ }));
    const undo = await findReceiptUndo("Undo");
    expect(undo.tagName).toBe("BUTTON");
    expect(undo).toHaveClass("sk-btn--quiet", "sk-btn--compact");
    // The Ångra is the bar's, in the one polite status slot at the foot of the view; it is not a notice.
    expect(undo.closest(".sk-receipt-slot")).toBe(receiptSlot());
    expect(receiptSlot().parentElement?.lastElementChild).toBe(receiptSlot());
    expect(undo.closest(".sk-notice")).toBeNull();
    const row = container.querySelector<HTMLElement>(".shopping-held-item")!;
    expect(row).toBe(openRow);
    // The row has no Ångra and keeps the room of its quick controls (unseen), so its height does not change.
    expect(within(row).queryByRole("button", { name: /Undo/ })).toBeNull();
    expect(row.querySelector(".shopping-quick-held")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    // "Bought" stands in the room of the quick controls, hidden from assistive technology; the amount keeps its place.
    expect(
      row.querySelector(".shopping-quick-held .shopping-held"),
    ).toHaveTextContent(shoppingEn.bought);
    expect(row.querySelector(".shopping-store-qty")).toHaveTextContent("2 l");
    // The one status (role="status") tells assistive technology what happened.
    expect(container.querySelectorAll('[role="status"]')).toHaveLength(1);
    expect(container.querySelector('[role="status"]')).toHaveTextContent(
      `${shoppingEn.bought}: Milk`,
    );
    expect(container.querySelector(".shopping-undo-item")).toBeNull();
  });
});

it("fullscreen marks its section, so the fullscreen rules apply", () => {
  const { container } = render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
  expect(container.querySelector("section")).toHaveClass("shopping-fullscreen");
});

describe("the purchased section", () => {
  it("the Purchased fold is the shared fold row with ⌄ (an icon) last, turned up when it is open, inline and in fullscreen", async () => {
    const user = userEvent.setup();
    const bought: ShoppingItem = {
      ...milk,
      id: "019f0000-0000-7000-8000-0000000000a2",
      name: "Eggs",
      purchased: true,
    };
    for (const fullscreen of [true, false]) {
      const { container, unmount } = render(
        <ShoppingView
          transport={adapter()}
          labels={shoppingEn}
          initial={{ ...detail, items: [milk, bought] }}
          fullscreen={fullscreen}
        />,
      );
      const fold = container.querySelector(".shopping-purchased > button");
      expect(fold).toHaveClass("sk-fold");
      expect(fold).toHaveTextContent(shoppingEn.boughtCount(1));
      expect(fold).toHaveAttribute("aria-expanded", "false");
      // The chevron is an SVG after the label, not a CSS pseudo-element.
      expect(fold?.lastElementChild?.tagName.toLowerCase()).toBe("svg");
      expect(container.querySelector(".shopping-purchased > ul")).toBeNull();
      await user.click(fold as HTMLElement);
      expect(fold).toHaveAttribute("aria-expanded", "true");
      expect(
        container.querySelector(".shopping-purchased > ul"),
      ).not.toBeNull();
      // One markup for both: no <details> and no own toggle class.
      expect(container.querySelector("details")).toBeNull();
      expect(container.querySelector(".shopping-bought-toggle")).toBeNull();
      unmount();
    }
  });
});
