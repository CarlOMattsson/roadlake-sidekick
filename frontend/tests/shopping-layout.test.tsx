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
import { readStylesheet } from "./helpers/stylesheet";

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

const css = readStylesheet("features/shopping-app/shopping.css");
const foldCss = readStylesheet("features/mcp-apps/ui/row.css");
const familyCss = readStylesheet("features/mcp-apps/ui/family.css");

describe("loading does not move the content", () => {
  it("the loading line is a badge taken out of the flow", async () => {
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
    expect(css.rule(".sidekick-shopping > .shopping-loading").position).toBe(
      "absolute",
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
      name: `${shoppingEn.undoPurchase}: Milk`,
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
    expect(container.querySelector('[role="status"]')).toBeNull();
    expect(container.querySelector(".shopping-undo-item")).toBeNull();
  });

  it("the Ångra target is 48 px: the 40 px compact button gets a 4 px area past its edge on each side", () => {
    // The size comes from the shared compact button (family.css), not from a rule of the shopping list's own.
    expect(familyCss.rule(".sk-btn--compact")["min-height"]).toBe(
      "var(--sk-compact)",
    );
    expect(familyCss.rule(".sk-btn--compact::after").inset).toBe(
      "calc(-4px - var(--sk-hairline))",
    );
  });

  it("the list has no sticky Ångra and no room reserved for one", () => {
    expect(css.rules.map((rule) => rule.declarations.position)).not.toContain(
      "sticky",
    );
  });

  it("the rows have no hairline between them; the space separates them", () => {
    const rule = css.rule(".shopping-items > li");
    // The row template's own air, not 12.
    expect(rule).toHaveProperty(["padding"], "var(--sk-row-pad) 0");
    expect(
      Object.keys(rule).filter((name) => name.startsWith("border")),
    ).toEqual([]);
  });
});

it("fullscreen keeps 6rem of bottom room for the host's reply field", () => {
  const { container } = render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingEn}
      initial={detail}
      fullscreen
    />,
  );
  expect(container.querySelector("section")).toHaveClass("shopping-fullscreen");
  const reserve = css.rule(".sidekick-shopping.shopping-fullscreen");
  expect(reserve).toHaveProperty(
    ["padding-bottom"],
    "var(--sk-foot-reserve, 6rem)",
  );
  expect(reserve["padding-bottom"]).not.toContain("--host-safe-bottom");
});

describe("phone sizes (PF-9)", () => {
  it("the text fallback is 16 px, so iOS does not zoom in on fields", () => {
    expect(css.rule(".sidekick-shopping")).toHaveProperty(
      ["font-size"],
      "var(--font-text-md-size, 16px)",
    );
  });

  it("a toolbar field gets its own row basis, so the list picker is not squeezed beside the buttons", () => {
    expect(
      css.rule(
        ".sidekick-shopping .shopping-toolbar > label:not(.shopping-check)",
      ),
    ).toHaveProperty(["flex"], "1 1 12rem");
  });
});

describe("store rows are dense but keep the 44 px tap target", () => {
  it("a store row is 48 px high (48 px, not 3rem): the large tap target", () => {
    expect(css.rule(".sidekick-shopping .shopping-store-row")).toHaveProperty(
      ["min-height"],
      "48px",
    );
  });

  it("the amount ends on the content edge, with tabular figures and no fixed width", () => {
    const rule = css.rule(".sidekick-shopping .shopping-store-qty");
    expect(rule).not.toHaveProperty(["margin-inline-end"]);
    expect(rule).toHaveProperty(["font-variant-numeric"], "tabular-nums");
    expect(rule).not.toHaveProperty(["min-width"]);
    expect(rule).not.toHaveProperty(["text-align"]);
  });

  it("the + Add item row of a card is 48 px high, the + on the ring's column (fullscreen has the + in the Back row instead)", () => {
    expect(css.rule(".sidekick-shopping .shopping-add-row")).toHaveProperty(
      ["min-height"],
      "var(--sk-tap-lg)",
    );
  });

  it("the store list item has no padding of its own", () => {
    expect(css.rule(".shopping-items > li.shopping-store-item")).toHaveProperty(
      ["padding"],
      "0",
    );
  });

  it("batch names are not clipped by CSS; the card counts the rest instead", () => {
    expect(css.rule(".shopping-batch-names")).not.toHaveProperty([
      "-webkit-line-clamp",
    ]);
  });
});

describe("the fullscreen progress stripe and the purchased section", () => {
  it("the progress is one line: the meta text, then the 6 px bar to the content edge, 12 after it", () => {
    const track = css.rule(
      ".sidekick-shopping .shopping-progress > .sk-progress > .sk-progress__track",
    );
    expect(track).toHaveProperty(["flex"], "1 1 auto");
    expect(track).toHaveProperty(["min-width"], "0");
    expect(track).toHaveProperty(["height"], "6px");
    const line = css.rule(
      ".sidekick-shopping .shopping-progress > .sk-progress",
    );
    expect(line).toHaveProperty(["display"], "flex");
    expect(line).toHaveProperty(["align-items"], "center");
    expect(line).toHaveProperty(["gap"], "var(--sk-s3)");
    expect(line).not.toHaveProperty(["flex-direction"], "column");
  });

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
    // The old rules are gone; the shared rule (row.css) turns the icon up while open.
    const selectors = css.rules.map((rule) => rule.selector).join("\n");
    expect(selectors).not.toContain("shopping-purchased > summary");
    expect(selectors).not.toContain("shopping-bought-toggle");
    expect(foldCss.rule('.sk-fold[aria-expanded="true"] > svg')).toHaveProperty(
      ["transform"],
      "rotate(180deg)",
    );
  });
});

describe("the inline card and the failure notice", () => {
  it("a card title and a card item wrap to two lines before they are clipped", () => {
    for (const [source, selector] of [
      [familyCss, ".sk-card__title"],
      [css, ".shopping-card-item"],
    ] as const) {
      const rule = source.rule(selector);
      expect(rule).toHaveProperty(["-webkit-line-clamp"], "2");
      expect(rule).toHaveProperty(["-webkit-box-orient"], "vertical");
      expect(rule["white-space"]).not.toBe("nowrap");
    }
  });

  it("the failure notice puts its actions on their own row under the message", () => {
    expect(
      css.rule(".sidekick-shopping .shopping-failure-actions"),
    ).toHaveProperty(["flex-wrap"], "wrap");
  });
});

describe("the compact inline card fits a phone screen", () => {
  it("a store heading is one line of small text, cut with an ellipsis", () => {
    const rule = css.rule(".shopping-folded .shopping-group > h3");
    expect(rule).toHaveProperty(["white-space"], "nowrap");
    expect(rule).toHaveProperty(["text-overflow"], "ellipsis");
    expect(rule).toHaveProperty(["font-size"], "0.8rem");
  });

  it("the add field and its button share one row, both 44 px high", () => {
    expect(css.rule(".shopping-folded .shopping-batch")).toHaveProperty(
      ["grid-template-columns"],
      "minmax(0, 1fr) auto",
    );
    expect(
      css.rule(".shopping-folded .shopping-batch > button"),
    ).toHaveProperty(["min-height"], "2.75rem");
  });

  it("an open row is the 44 px tap target with no padding of its own", () => {
    expect(css.rule(".shopping-items--folded > li")).toHaveProperty(
      ["padding"],
      "0",
    );
    expect(
      css.rule(".sidekick-shopping .shopping-items--folded .shopping-check"),
    ).toHaveProperty(["min-height"], "2.75rem");
  });
});
