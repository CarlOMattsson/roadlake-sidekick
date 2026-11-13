import { render, screen, waitFor, within } from "@testing-library/react";
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
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
    id: "019f0000-0000-7000-8000-0000000000a0",
    list_id: list.id,
    name: "Item",
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

// Five open items; the failing one is the last, far down the list.
const rows = [1, 2, 3, 4, 5].map((n) =>
  item({
    id: `019f0000-0000-7000-8000-0000000000b${n}`,
    name: `Item ${n}`,
  }),
);
const last = rows[4]!;

const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: rows,
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
      item: { ...last, purchased: true, version: 2 },
    }),
    ...over,
  };
}

describe("a failed row write shows its notice in that row", () => {
  it("the notice is one short line in the failing row with Try again and Refresh as text buttons, and takes focus", async () => {
    const user = userEvent.setup();
    const transport = adapter();
    vi.mocked(transport.purchase)
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValueOnce({
        item: { ...last, purchased: true, version: 2 },
      });
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detail}
      />,
    );
    await user.click(screen.getByRole("checkbox", { name: /Item 5/ }));

    const alert = await screen.findByRole("alert");
    const row = screen.getByRole("checkbox", { name: /Item 5/ }).closest("li");
    expect(row).toContainElement(alert);
    expect(screen.getAllByRole("alert")).toHaveLength(1);
    await waitFor(() =>
      expect(alert.closest(".shopping-failure")).toHaveFocus(),
    );

    const paragraph = alert.querySelector("p");
    expect(paragraph).toHaveTextContent(shoppingEn.markFailed);
    expect(alert).not.toHaveTextContent(shoppingEn.failed);
    expect(shoppingSv.markFailed).toBe("Ändringen kunde inte sparas.");
    const retry = within(alert).getByRole("button", { name: shoppingEn.retry });
    expect(paragraph).not.toContainElement(retry);
    expect(retry).toHaveClass("sk-error-retry--text");
    expect(retry.parentElement).toHaveClass("sk-error__actions");
    expect(
      within(alert).getByRole("button", { name: shoppingEn.refresh }),
    ).toBeInTheDocument();

    await user.click(retry);
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [, failedKey] = vi.mocked(transport.purchase).mock.calls[0]!;
    const [, retryKey] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(retryKey).toBe(failedKey);
    await waitFor(() =>
      expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
    );
  });

  it("in the store view the notice sits in the failing store row", async () => {
    const user = userEvent.setup();
    const transport = adapter();
    vi.mocked(transport.purchase).mockRejectedValueOnce(new Error("network"));
    render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detail}
        fullscreen
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Mark Item 5 as bought" }),
    );

    const alert = await screen.findByRole("alert");
    const row = screen
      .getByRole("button", { name: "Mark Item 5 as bought" })
      .closest("li");
    expect(row).toHaveClass("shopping-store-item");
    expect(row).toContainElement(alert);
    await waitFor(() =>
      expect(alert.closest(".shopping-failure")).toHaveFocus(),
    );
    expect(alert).toHaveTextContent(shoppingEn.markFailed);
    expect(
      within(alert).getByRole("button", { name: shoppingEn.retry }),
    ).toBeInTheDocument();
  });
});

describe("a failed read stays at the top of the list", () => {
  it("a list that cannot be read shows its notice above the rows, with the actions on their own row", async () => {
    const transport = adapter({
      lists: vi.fn().mockRejectedValue(new Error("network")),
    });
    const { container } = render(
      <ShoppingView
        transport={transport}
        labels={shoppingEn}
        initial={detail}
      />,
    );

    const alert = await screen.findByRole("alert");
    expect(alert.closest("li")).toBeNull();
    expect(alert.closest("section")).toBe(
      container.querySelector("section.sidekick-shopping"),
    );
    expect(
      alert.compareDocumentPosition(
        container.querySelector(".shopping-items")!,
      ),
    ).toBe(Node.DOCUMENT_POSITION_FOLLOWING);
    await waitFor(() => expect(alert).toHaveFocus());
    expect(alert.querySelector("p")).toHaveTextContent(shoppingEn.failed);
    expect(
      within(alert).queryByRole("button", { name: shoppingEn.retry }),
    ).not.toBeInTheDocument();
    const refresh = within(alert).getByRole("button", {
      name: shoppingEn.refresh,
    });
    expect(alert.querySelector("p")).not.toContainElement(refresh);
    expect(refresh.parentElement).toHaveClass("shopping-failure-actions");
    // The rows the list already showed stay in place.
    expect(
      screen.getByRole("checkbox", { name: /Item 1/ }),
    ).toBeInTheDocument();
  });
});
