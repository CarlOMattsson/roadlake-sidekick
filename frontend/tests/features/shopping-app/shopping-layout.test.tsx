import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn } from "@/features/shopping-app/labels";
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

describe("a bought row holds its Ångra in place", () => {
  it("the Ångra is a compact secondary button beside the row's text, not a notice", async () => {
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
    await user.click(screen.getByRole("button", { name: /^Mark Milk as/ }));
    const undo = await screen.findByRole("button", {
      name: shoppingEn.undoPurchaseNamed("Milk", true),
    });
    expect(undo.tagName).toBe("BUTTON");
    expect(undo).toHaveClass("sk-btn--secondary", "sk-btn--compact");
    expect(undo).not.toHaveClass("sk-btn--tonal");
    expect(undo.closest("li")).toHaveClass("shopping-held-item");
    // A sibling of the row's line (ring and open button), never inside the meta line ("Bought · 2 l").
    expect(undo.parentElement).toBe(undo.closest("li"));
    expect(undo.closest(".shopping-held")).toBeNull();
    expect(
      undo.closest("li")!.querySelector(".shopping-held"),
    ).toHaveTextContent(`${shoppingEn.bought} · 2 l`);
    expect(undo.closest(".sk-notice")).toBeNull();
    // The visible line is for the eye; the row's one status (role="status") tells assistive technology what happened.
    expect(undo.closest("li")!.querySelector(".shopping-held")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
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
