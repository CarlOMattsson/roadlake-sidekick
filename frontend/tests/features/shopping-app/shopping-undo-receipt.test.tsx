import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { elementWithText } from "@tests/helpers/exact-text";
import {
  findReceiptUndo,
  receiptNow,
  receiptSlot,
  receiptText,
  receiptRunning,
} from "@tests/helpers/receipt-bar";

const list: ShoppingList = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};

function item(over: Partial<ShoppingItem>): ShoppingItem {
  return {
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
    ...over,
  };
}

const milk = item({});
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Eggs",
  purchased: true,
});

function detail(items: ShoppingItem[]): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items,
  };
}

/** A server that flips the purchased flag and bumps the version; reads answer what was last stored. */
function server(items: ShoppingItem[]): ShoppingTransport {
  const stored = new Map(items.map((entry) => [entry.id, entry]));
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn(() => Promise.resolve(detail([...stored.values()]))),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn((current: ShoppingItem) => {
      const next = {
        ...current,
        purchased: !current.purchased,
        version: current.version + 1,
      };
      stored.set(next.id, next);
      return Promise.resolve({ item: next });
    }),
  };
}

afterEach(() => {
  vi.useRealTimers();
});

function renderView(
  transport: ShoppingTransport,
  items: ShoppingItem[],
  props: Partial<Parameters<typeof ShoppingView>[0]> = {},
) {
  return render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail(items)}
      {...props}
    />,
  );
}

async function settle() {
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
}

describe.each([
  { view: "inline card", props: {} },
  { view: "fullscreen room", props: { fullscreen: true } },
])("buying an item in the $view", ({ props }) => {
  async function buyMilk() {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const transport = server([milk]);
    const user = userEvent.setup({
      advanceTimers: (ms) => {
        if (vi.isFakeTimers()) vi.advanceTimersByTime(ms);
      },
    });
    renderView(transport, [milk], props);
    await settle();
    // Every mode ticks the row's ring.
    await user.click(
      screen.getByRole("button", { name: shoppingEn.markBought("Milk") }),
    );
    const undo = await findReceiptUndo("Undo");
    await waitFor(() => expect(undo).toBeEnabled());
    await receiptRunning();
    return { transport, user, undo };
  }

  it("says what happened in the bar, the row keeps its place, and Ångra takes it back against the new version", async () => {
    const { transport, user, undo } = await buyMilk();
    expect(receiptText()).toBe(`${shoppingEn.bought}: Milk`);
    expect(screen.getByRole("status")).toHaveTextContent(
      `${shoppingEn.bought}: Milk`,
    );
    expect(undo).toHaveTextContent(/^Undo$/);
    // The row is the row's state, not a receipt: muted in its place with "Bought", and no Ångra of its own.
    const row = document.querySelector<HTMLElement>(".shopping-held-item")!;
    expect(row).toHaveTextContent("Milk");
    expect(row.querySelector(".shopping-held")).toHaveTextContent(
      shoppingEn.bought,
    );
    expect(within(row).queryByRole("button", { name: /Undo/ })).toBeNull();
    await user.click(undo);
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [first, firstKey] = vi.mocked(transport.purchase).mock.calls[0]!;
    const [back, backKey] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(first).toMatchObject({ id: milk.id, purchased: false, version: 1 });
    expect(back).toMatchObject({ id: milk.id, purchased: true, version: 2 });
    expect(backKey).not.toBe(firstKey);
    await waitFor(() =>
      expect(document.querySelector(".shopping-loading")).toBeNull(),
    );
    await waitFor(() => expect(receiptNow()).toBeNull());
    expect(document.querySelector(".shopping-held-item")).toBeNull();
  });

  it("holds the row for UNDO_MS, then it moves to Köpta", async () => {
    await buyMilk();
    // While the bar shows the row stands in its place, and "Köpta" does not count it yet.
    expect(screen.queryByRole("button", { name: /^Bought/ })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 1_000);
    });
    expect(receiptNow()).not.toBeNull();
    expect(document.querySelector(".shopping-held-item")).not.toBeNull();
    expect(screen.queryByRole("button", { name: /^Bought/ })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(receiptNow()).toBeNull();
    // The slot stays in the page (a polite live region) and is empty.
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
    expect(document.querySelector(".shopping-held-item")).toBeNull();
    // The bought item is listed under Köpta (1), no longer among the open rows.
    expect(
      elementWithText(shoppingEn.boughtCount(1), "button"),
    ).toBeInTheDocument();
  });

  it("stands still while the pointer is over the bar, and runs on when it leaves", async () => {
    await buyMilk();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 1_000);
    });
    const bar = receiptNow()!;
    fireEvent.pointerEnter(bar);
    expect(bar).toHaveAttribute("data-held");
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(receiptNow()).not.toBeNull();
    fireEvent.pointerLeave(bar);
    expect(bar).not.toHaveAttribute("data-held");
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(receiptNow()).toBeNull();
  });

  it("stands still while focus is in Ångra", async () => {
    const { undo } = await buyMilk();
    act(() => undo.focus());
    act(() => {
      vi.advanceTimersByTime(UNDO_MS * 2);
    });
    expect(receiptNow()).not.toBeNull();
    act(() => undo.blur());
    act(() => {
      vi.advanceTimersByTime(UNDO_MS + 100);
    });
    expect(receiptNow()).toBeNull();
  });

  it("has the bar in the page before any change: one empty polite live region", async () => {
    renderView(server([milk]), [milk], props);
    await settle();
    const slot = receiptSlot();
    expect(slot).toHaveAttribute("role", "status");
    expect(slot).toHaveAttribute("aria-live", "polite");
    expect(slot).toBeEmptyDOMElement();
  });
});

it("says 'Köpt' in Swedish and 'Bought' in English", async () => {
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={server([milk])}
      labels={shoppingSv}
      initial={detail([milk])}
    />,
  );
  await settle();
  await user.click(
    screen.getByRole("button", { name: shoppingSv.markBought("Milk") }),
  );
  expect(await screen.findByRole("status")).toHaveTextContent("Köpt: Milk");
  expect(shoppingEn.bought).toBe("Bought");
});

describe("ticking a bought item back to open", () => {
  async function untickEggs() {
    const transport = server([eggs]);
    const user = userEvent.setup();
    renderView(transport, [eggs]);
    await settle();
    await user.click(elementWithText(shoppingEn.boughtCount(1), "button"));
    await user.click(
      screen.getByRole("button", { name: shoppingEn.markOpen("Eggs") }),
    );
    const undo = await findReceiptUndo("Undo");
    return { transport, user, undo };
  }

  it("says 'Not bought' with Ångra, which buys it again against the new version", async () => {
    const { transport, user, undo } = await untickEggs();
    expect(screen.getByRole("status")).toHaveTextContent(
      `${shoppingEn.notBought}: Eggs`,
    );
    const row = document.querySelector<HTMLElement>(".shopping-held-item")!;
    expect(row).toHaveTextContent("Eggs");
    expect(row.querySelector(".shopping-held")).toHaveTextContent(
      shoppingEn.notBought,
    );
    await waitFor(() => expect(undo).toBeEnabled());
    await user.click(undo);
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [back] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(back).toMatchObject({ id: eggs.id, purchased: false, version: 2 });
    await waitFor(() => expect(receiptNow()).toBeNull());
  });

  it("takes the change back from the held row's ring too, and the bar then offers no second Ångra", async () => {
    const { transport, user } = await untickEggs();
    const row = document.querySelector<HTMLElement>(".shopping-held-item")!;
    // The held row now reads as open ("Mark bought"); a tap on its ring takes the change back.
    await user.click(
      within(row).getByRole("button", { name: shoppingEn.markBought("Eggs") }),
    );
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [back] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(back).toMatchObject({ id: eggs.id, purchased: false, version: 2 });
    // The bar says what happened, without Ångra (the change it would undo is already taken back).
    expect(receiptText()).toBe(`${shoppingEn.bought}: Eggs`);
    expect(
      within(receiptSlot()).queryByRole("button", { name: "Undo" }),
    ).toBeNull();
  });

  it("in Swedish the receipt is 'Inte köpt'", () => {
    expect(shoppingSv.notBought).toBe("Inte köpt");
    expect(shoppingEn.notBought).toBe("Not bought");
  });
});

/** A server with two lists, so the picker is shown instead of the only list. */
function twoLists(): ShoppingTransport {
  const transport = server([milk]);
  vi.mocked(transport.lists).mockResolvedValue({
    lists: [
      { ...list, open_count: 1 },
      {
        ...list,
        id: `${list.id.slice(0, -1)}2`,
        name: "Garden",
        open_count: 0,
      },
    ],
    next_offset: null,
  });
  return transport;
}

describe("the ⋯ menu", () => {
  it("is the family's panel in the picker, with Minne och kontroll, and Escape closes it back to ⋯", async () => {
    const user = userEvent.setup();
    const onNavigate = vi.fn();
    render(
      <ShoppingView
        transport={twoLists()}
        labels={shoppingSv}
        fullscreen
        onNavigate={onNavigate}
      />,
    );
    const more = await screen.findByRole("button", {
      name: shoppingSv.moreActions,
    });
    await user.click(more);
    const entry = screen.getByRole("button", { name: "Minne och kontroll" });
    expect(entry).toHaveClass("sk-menu-item");
    expect(entry.parentElement).toHaveClass("sk-menu-panel");
    await user.tab();
    expect(entry).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: "Minne och kontroll" }),
    ).toBeNull();
    expect(more).toHaveFocus();
    await user.click(more);
    await user.click(
      screen.getByRole("button", { name: "Minne och kontroll" }),
    );
    expect(onNavigate).toHaveBeenCalledWith({
      room: "control",
      view: "memory",
    });
    expect(
      screen.queryByRole("button", { name: "Minne och kontroll" }),
    ).toBeNull();
  });

  it("holds the host's own settings in the picker instead of Control", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <ShoppingView
        transport={twoLists()}
        labels={shoppingEn}
        fullscreen
        hostSettings={{ label: "Settings", onOpen }}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: shoppingEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: "Settings" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("has no ⋯ in the picker when the room cannot open anything", async () => {
    render(
      <ShoppingView transport={twoLists()} labels={shoppingEn} fullscreen />,
    );
    await screen.findByRole("heading", { name: shoppingEn.lists });
    expect(
      screen.queryByRole("button", { name: shoppingEn.moreActions }),
    ).toBeNull();
  });

  it("rows of a list's ⋯ are 'Edit list' and the control entry; Escape closes it back to ⋯", async () => {
    const user = userEvent.setup();
    renderView(server([milk]), [milk], {
      fullscreen: true,
      onNavigate: vi.fn(),
    });
    await settle();
    const more = screen.getByRole("button", { name: shoppingEn.moreActions });
    await user.click(more);
    const edit = screen.getByRole("button", { name: shoppingEn.editList });
    expect(edit).toHaveClass("sk-menu-item");
    expect(edit.parentElement).toHaveClass("sk-menu-panel");
    expect(
      screen.getByRole("button", { name: "Memory and control" }),
    ).toHaveClass("sk-menu-item");
    // Escape from the trigger itself also closes the panel.
    more.focus();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: shoppingEn.editList }),
    ).toBeNull();
    expect(more).toHaveFocus();
  });
});

describe("the item form", () => {
  it("ends with Save as the primary and Cancel as a quiet button in the family's actions row", async () => {
    const user = userEvent.setup();
    renderView(server([milk]), [milk], { fullscreen: true });
    await settle();
    await user.click(screen.getByRole("button", { name: /^Milk/ }));
    const save = await screen.findByRole("button", { name: shoppingEn.save });
    const cancel = screen.getByRole("button", { name: shoppingEn.cancel });
    expect(save).toHaveClass("sk-btn--primary");
    expect(cancel).toHaveClass("sk-btn--quiet");
    expect(save.parentElement).toHaveClass("sk-form-actions");
    expect(cancel.parentElement).toBe(save.parentElement);
  });
});

describe("Swedish empty states", () => {
  it("say 'än', not 'ännu'", () => {
    expect(shoppingSv.empty).toBe("Inga varor än.");
    expect(shoppingSv.noLists).toBe("Inga listor än.");
  });
});
