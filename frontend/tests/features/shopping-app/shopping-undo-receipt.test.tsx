import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
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

const undoName = (name: string) => new RegExp(`^Undo (not )?bought ${name}$`);

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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
}

describe.each([
  { view: "list view", props: {} },
  { view: "store view", props: { fullscreen: true } },
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
    // The list view ticks a checkbox, the store view its ring.
    await user.click(
      screen.queryByRole("checkbox", { name: /^Milk/ }) ??
        screen.getByRole("button", { name: shoppingEn.markBought("Milk") }),
    );
    const undo = await screen.findByRole("button", { name: undoName("Milk") });
    await waitFor(() => expect(undo).toBeEnabled());
    return { transport, user, undo };
  }

  it("says what happened in the row's status, and Ångra takes it back against the new version", async () => {
    const { transport, user, undo } = await buyMilk();
    expect(screen.getByRole("status")).toHaveTextContent(
      `${shoppingEn.bought}: Milk`,
    );
    expect(undo).toHaveAccessibleName("Undo bought Milk");
    expect(undo).toHaveTextContent(/^Undo$/);
    await user.click(undo);
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [first, firstKey] = vi.mocked(transport.purchase).mock.calls[0]!;
    const [back, backKey] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(first).toMatchObject({ id: milk.id, purchased: false, version: 1 });
    expect(back).toMatchObject({ id: milk.id, purchased: true, version: 2 });
    expect(backKey).not.toBe(firstKey);
    await waitFor(() =>
      expect(screen.queryByRole("status")).not.toBeInTheDocument(),
    );
    expect(screen.queryByRole("button", { name: undoName("Milk") })).toBeNull();
  });

  it("holds the row for UNDO_MS, then it moves to Köpta", async () => {
    await buyMilk();
    // While Ångra holds the row stands in its place, and "Köpta" does not count it yet.
    expect(screen.queryByRole("button", { name: /^Bought/ })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 1_000);
    });
    expect(
      screen.getByRole("button", { name: undoName("Milk") }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /^Bought/ })).toBeNull();
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(screen.queryByRole("button", { name: undoName("Milk") })).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
    // The bought item is listed under Köpta (1), no longer among the open rows.
    expect(
      elementWithText(shoppingEn.boughtCount(1), "button"),
    ).toBeInTheDocument();
  });

  it("stands still while the pointer is over Ångra, and runs on when it leaves", async () => {
    const { undo } = await buyMilk();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS - 1_000);
    });
    fireEvent.pointerEnter(undo);
    expect(undo).toHaveAttribute("data-held");
    act(() => {
      vi.advanceTimersByTime(60_000);
    });
    expect(
      screen.getByRole("button", { name: undoName("Milk") }),
    ).toBeInTheDocument();
    fireEvent.pointerLeave(undo);
    expect(undo).not.toHaveAttribute("data-held");
    act(() => {
      vi.advanceTimersByTime(1_500);
    });
    expect(screen.queryByRole("button", { name: undoName("Milk") })).toBeNull();
  });

  it("stands still while focus is in Ångra", async () => {
    const { undo } = await buyMilk();
    act(() => undo.focus());
    act(() => {
      vi.advanceTimersByTime(UNDO_MS * 2);
    });
    expect(
      screen.getByRole("button", { name: undoName("Milk") }),
    ).toBeInTheDocument();
    act(() => undo.blur());
    act(() => {
      vi.advanceTimersByTime(UNDO_MS + 100);
    });
    expect(screen.queryByRole("button", { name: undoName("Milk") })).toBeNull();
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
  await user.click(screen.getByRole("checkbox", { name: /^Milk/ }));
  expect(await screen.findByRole("status")).toHaveTextContent("Köpt: Milk");
  expect(shoppingEn.bought).toBe("Bought");
});

describe("ticking a bought item back to open", () => {
  it("says 'Not bought' with Ångra, which buys it again against the new version", async () => {
    const transport = server([eggs]);
    const user = userEvent.setup();
    renderView(transport, [eggs]);
    await settle();
    await user.click(elementWithText(shoppingEn.boughtCount(1), "button"));
    await user.click(screen.getByRole("checkbox", { name: /^Eggs/ }));
    const undo = await screen.findByRole("button", { name: undoName("Eggs") });
    expect(screen.getByRole("status")).toHaveTextContent(
      `${shoppingEn.notBought}: Eggs`,
    );
    expect(undo.closest("li")).toHaveClass("shopping-held-item");
    expect(
      undo.closest("li")!.querySelector(".shopping-status"),
    ).toHaveTextContent(shoppingEn.notBought);
    await waitFor(() => expect(undo).toBeEnabled());
    await user.click(undo);
    await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
    const [back] = vi.mocked(transport.purchase).mock.calls[1]!;
    expect(back).toMatchObject({ id: eggs.id, purchased: false, version: 2 });
    await waitFor(() => expect(screen.queryByRole("status")).toBeNull());
  });

  it("names Ångra after the item and what it takes back, while its visible text stays 'Undo'", async () => {
    const user = userEvent.setup();
    renderView(server([eggs]), [eggs]);
    await settle();
    await user.click(elementWithText(shoppingEn.boughtCount(1), "button"));
    await user.click(screen.getByRole("checkbox", { name: /^Eggs/ }));
    const undo = await screen.findByRole("button", {
      name: "Undo not bought Eggs",
    });
    expect(undo).toHaveTextContent(/^Undo$/);
    expect(shoppingSv.undoPurchaseNamed("Mjölk", true)).toBe(
      "Ångra köpt Mjölk",
    );
    expect(shoppingSv.undoPurchaseNamed("Mjölk", false)).toBe(
      "Ångra inte köpt Mjölk",
    );
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
