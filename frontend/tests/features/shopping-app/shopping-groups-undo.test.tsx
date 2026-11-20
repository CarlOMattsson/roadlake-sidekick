import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { elementWithText } from "@tests/helpers/exact-text";
import {
  findReceiptUndo,
  receiptNow,
  receiptText,
  receiptRunning,
} from "@tests/helpers/receipt-bar";

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
    store: "ICA MAXI 4",
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 1,
    ...over,
  };
}

const milk = item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" });
const lamp = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Lamp",
  store: null,
});
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a3",
  name: "Eggs",
  purchased: true,
});

function detail(
  items: ShoppingItem[],
  over: Partial<ShoppingDetail> = {},
): ShoppingDetail {
  return {
    shopping_list: list,
    evaluated_on: "2026-10-24",
    next_offset: null,
    items,
    ...over,
  };
}

function adapter(read: ShoppingDetail): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(read),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    // Answers like the server: the item with the flipped purchased flag and a new version.
    purchase: vi.fn((item: ShoppingItem) =>
      Promise.resolve({
        item: {
          ...item,
          purchased: !item.purchased,
          version: item.version + 1,
        },
      }),
    ),
  };
}

/** The ring that marks an open row bought. */
function ring(name: string): HTMLElement {
  return screen.getByRole("button", { name: shoppingEn.markBought(name) });
}

/**
 * The row of an item that the last tick holds in its place inside its shop group. The Ångra is not on the row: it is
 * the receipt bar's (`findReceiptUndo`).
 */
async function heldRow(name: string): Promise<HTMLElement> {
  const held = await waitFor(() => {
    const row = [
      ...document.querySelectorAll<HTMLElement>(
        ".shopping-group .shopping-held-item",
      ),
    ].find(
      (entry) =>
        entry.querySelector(".shopping-store-name")?.textContent === name,
    );
    if (!row) throw new Error(`no held row for ${name} in its group`);
    return row;
  });
  // The receipt that holds it counts its time from here: the tests move the fake clock next.
  await receiptRunning();
  return held;
}

function groupOf(row: HTMLElement): HTMLElement {
  return row.closest("section.shopping-group")!;
}

it("open items without a store sit under their own No store heading", () => {
  render(
    <ShoppingView
      transport={adapter(detail([milk, lamp]))}
      labels={shoppingEn}
      initial={detail([milk, lamp])}
    />,
  );
  const heading = screen.getByRole("heading", {
    level: 3,
    name: shoppingEn.otherStore,
  });
  const group = heading.closest("section")!;
  expect(within(group).getByText("Lamp")).toBeInTheDocument();
  // The item without a store is not listed under a store heading.
  expect(within(group).queryByText("Milk")).not.toBeInTheDocument();
});

it("the Swedish label for items without a store is Utan butik", () => {
  render(
    <ShoppingView
      transport={adapter(detail([milk, lamp]))}
      labels={shoppingSv}
      initial={detail([milk, lamp])}
    />,
  );
  expect(
    screen.getByRole("heading", { level: 3, name: "Utan butik" }),
  ).toBeInTheDocument();
});

it("Köpta shows its items once the section is opened", () => {
  render(
    <ShoppingView
      transport={adapter(detail([milk, eggs]))}
      labels={shoppingEn}
      initial={detail([milk, eggs])}
    />,
  );
  const fold = elementWithText(`${shoppingEn.purchased} (1)`, "button");
  const section = fold.closest("div")!;
  expect(section).toHaveClass("shopping-purchased");
  expect(within(section).queryByText("Eggs")).toBeNull();
  fireEvent.click(fold);
  expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(within(section).getByText("Eggs")).toBeVisible();
  // A bought row offers its ring to mark it open again.
  expect(
    within(section).getByRole("button", { name: shoppingEn.markOpen("Eggs") }),
  ).toBeVisible();
});

it("the page switcher is hidden on a single page and shown when there are more pages", () => {
  const { unmount } = render(
    <ShoppingView
      transport={adapter(detail([milk]))}
      labels={shoppingEn}
      initial={detail([milk])}
    />,
  );
  expect(
    screen.queryByText(`${shoppingEn.page} 1`, { exact: true }),
  ).not.toBeInTheDocument();
  unmount();
  render(
    <ShoppingView
      transport={adapter(detail([milk], { next_offset: 100 }))}
      labels={shoppingEn}
      initial={detail([milk], { next_offset: 100 })}
    />,
  );
  expect(
    screen.getByText(`${shoppingEn.page} 1`, { exact: true }),
  ).toBeInTheDocument();
});

it("ticking an item holds the row in its place as 'Bought'; the bar's Undo marks it open again", async () => {
  const bought = detail([{ ...milk, purchased: true }]);
  const transport = adapter(detail([milk]));
  // The read on mount shows the item open; the reads after the write show it bought.
  vi.mocked(transport.get)
    .mockResolvedValueOnce(detail([milk]))
    .mockResolvedValue(bought);
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  const row = await heldRow("Milk");
  // The row stays where it was. Its line says "Bought" in the amount's place; it has no Ångra of its own.
  expect(row.querySelector(".shopping-held")).toHaveTextContent(
    shoppingEn.bought,
  );
  expect(within(row).queryByRole("button", { name: /Undo/ })).toBeNull();
  // The Ångra is in the bar: a compact quiet button next to the message.
  const undoButton = await findReceiptUndo("Undo");
  expect(undoButton).toHaveClass("sk-btn--quiet", "sk-btn--compact");
  expect(receiptText()).toBe(`${shoppingEn.bought}: Milk`);
  expect(undoButton.closest(".sk-notice")).toBeNull();
  const [, firstKey] = vi.mocked(transport.purchase).mock.calls[0]!;
  await waitFor(() => expect(undoButton).toBeEnabled());
  await user.click(undoButton);
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
  // Undo sends the bought item back through the same purchase write: the adapter sends purchased=false.
  const [undone, undoKey] = vi.mocked(transport.purchase).mock.calls[1]!;
  // The Undo write is made against the version the purchase returned (2), not the list read before it.
  expect(undone).toMatchObject({ id: milk.id, purchased: true, version: 2 });
  expect(undoKey).toBeTruthy();
  expect(undoKey).not.toBe(firstKey);
  await waitFor(() => expect(receiptNow()).toBeNull());
});

it("a refused Undo of the bar shows Try again in the view once its row is folded away, and Try again repeats the same write with its key", async () => {
  const bought = { ...milk, purchased: true, version: 2 };
  const transport = adapter(detail([milk]));
  vi.mocked(transport.purchase)
    .mockResolvedValueOnce({ item: bought })
    .mockRejectedValueOnce(new Error("network"))
    .mockResolvedValueOnce({
      item: { ...bought, purchased: false, version: 3 },
    });
  vi.mocked(transport.get)
    .mockResolvedValueOnce(detail([milk]))
    .mockResolvedValue(detail([bought]));
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  await heldRow("Milk");
  const undoButton = await findReceiptUndo("Undo");
  await waitFor(() => expect(undoButton).toBeEnabled());
  await user.click(undoButton);
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
  // The refused Undo leaves the bar only once its write has run, and the row falls back to its bought state under the
  // closed Köpta fold. Its error names the item wherever the row is: under the row while drawn, else the view's box.
  await waitFor(() => expect(receiptNow()).toBeNull());
  await waitFor(() =>
    expect(document.querySelector(".sk-message--error")).not.toBeNull(),
  );
  const alert = screen.getByRole("alert");
  expect(alert).toHaveTextContent(shoppingEn.markFailed("Milk", false));
  await user.click(
    within(alert).getByRole("button", { name: shoppingEn.retry }),
  );
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(3));
  const [, failedKey] = vi.mocked(transport.purchase).mock.calls[1]!;
  const [retried, retryKey] = vi.mocked(transport.purchase).mock.calls[2]!;
  // The retry is the same Undo: the bought item at version 2, sent with the key of the failed attempt.
  expect(retried).toMatchObject({ id: milk.id, purchased: true, version: 2 });
  expect(retryKey).toBe(failedKey);
  await waitFor(() =>
    expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
  );
});

afterEach(() => {
  vi.useRealTimers();
});

/** Renders the list, ticks Milk and waits for its Ångra; the read after the write shows it bought. */
async function buyMilk() {
  const bought = detail([{ ...milk, purchased: true }]);
  const transport = adapter(detail([milk]));
  vi.mocked(transport.get)
    .mockResolvedValueOnce(detail([milk]))
    .mockResolvedValue(bought);
  const user = userEvent.setup({
    advanceTimers: (ms) => {
      if (vi.isFakeTimers()) vi.advanceTimersByTime(ms);
    },
  });
  const { rerender } = render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  await heldRow("Milk");
  const undoButton = await findReceiptUndo("Undo");
  await waitFor(() => expect(undoButton).toBeEnabled());
  return { transport, user, rerender };
}

it("Undo is still offered 9 s after the purchase and sends the item back", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { transport, user } = await buyMilk();
  act(() => {
    vi.advanceTimersByTime(9_000);
  });
  const undoButton = await findReceiptUndo("Undo");
  await user.click(undoButton);
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
  const [undone] = vi.mocked(transport.purchase).mock.calls[1]!;
  expect(undone).toMatchObject({ id: milk.id, purchased: true, version: 2 });
});

it("a re-render of the list during the Undo window keeps the bar's Ångra and the held row", async () => {
  const { transport, rerender } = await buyMilk();
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  const readsBefore = vi.mocked(transport.get).mock.calls.length;
  // A changed refreshKey reads the list again, as a write in the full view does.
  rerender(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk])}
      refreshKey={1}
    />,
  );
  await waitFor(() =>
    expect(vi.mocked(transport.get).mock.calls.length).toBeGreaterThan(
      readsBefore,
    ),
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  rerender(
    <ShoppingView
      transport={transport}
      labels={{ ...shoppingEn }}
      initial={detail([milk])}
      refreshKey={1}
    />,
  );
  const undoButton = await findReceiptUndo("Undo");
  expect(undoButton).toBeEnabled();
  expect(
    (await heldRow("Milk")).querySelector(".shopping-held"),
  ).toHaveTextContent(shoppingEn.bought);
  // Only the purchase itself was written; the re-render and the reload wrote nothing.
  expect(transport.purchase).toHaveBeenCalledTimes(1);
});

it("a purchase the server answers as still open is a failure, not a bought item", async () => {
  const transport = adapter(detail([milk]));
  vi.mocked(transport.purchase).mockResolvedValueOnce({ item: milk });
  const user = userEvent.setup();
  const { container } = render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  // A refused tick takes its receipt back: the bar never says "Bought" for it, and nothing is held.
  await waitFor(() => expect(receiptNow()).toBeNull());
  expect(container.querySelector(".shopping-held")).toBeNull();
});

it("a bought row keeps its place between its neighbours in the shop group", async () => {
  const bread = item({
    id: "019f0000-0000-7000-8000-0000000000a4",
    name: "Bread",
  });
  const pasta = item({
    id: "019f0000-0000-7000-8000-0000000000a5",
    name: "Pasta",
  });
  const transport = adapter(detail([bread, milk, pasta]));
  vi.mocked(transport.get)
    .mockResolvedValueOnce(detail([bread, milk, pasta]))
    .mockResolvedValue(detail([bread, { ...milk, purchased: true }, pasta]));
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([bread, milk, pasta])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  const row = await heldRow("Milk");
  // The bought row still stands between Bread and Pasta in the ICA MAXI 4 group.
  expect(row.previousElementSibling).toHaveTextContent(/^Bread/);
  expect(row.nextElementSibling).toHaveTextContent(/^Pasta/);
  // The group heading carries no count: it is the store's name alone.
  expect(groupOf(row).querySelector("h3")?.textContent).toBe(milk.store);
});

it("a bought row keeps its place when it was its group's last open row; the group stays", async () => {
  const transport = adapter(detail([milk, lamp]));
  vi.mocked(transport.get)
    .mockResolvedValueOnce(detail([milk, lamp]))
    .mockResolvedValue(detail([{ ...milk, purchased: true }, lamp]));
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk, lamp])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  const group = groupOf(await heldRow("Milk"));
  expect(group.querySelector("h3")?.textContent).toBe(milk.store);
  expect(group.querySelectorAll("li")).toHaveLength(1);
  // The No store group follows the held row's group, as before the purchase.
  expect(group.nextElementSibling?.querySelector("h3")).toHaveTextContent(
    shoppingEn.otherStore,
  );
});

/** A small server: the purchase flips the stored flag, and the reads show what is stored. */
function twoRowServer() {
  const bread = item({
    id: "019f0000-0000-7000-8000-0000000000a4",
    name: "Bread",
  });
  const stored = new Map<string, boolean>([
    [milk.id, false],
    [bread.id, false],
  ]);
  const transport = adapter(detail([milk, bread]));
  vi.mocked(transport.purchase).mockImplementation((current: ShoppingItem) => {
    stored.set(current.id, !current.purchased);
    return Promise.resolve({
      item: {
        ...current,
        purchased: !current.purchased,
        version: current.version + 1,
      },
    });
  });
  vi.mocked(transport.get).mockImplementation(() =>
    Promise.resolve(
      detail([
        { ...milk, purchased: stored.get(milk.id)! },
        { ...bread, purchased: stored.get(bread.id)! },
      ]),
    ),
  );
  return { transport, stored, bread };
}

it("two purchases hold both rows under one bar; its Ångra buys back only the last, and the other row is released with it", async () => {
  const { transport, stored, bread } = twoRowServer();
  const user = userEvent.setup();
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk, bread])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  await heldRow("Milk");
  await waitFor(() => expect(ring("Bread")).toBeEnabled());
  await user.click(ring("Bread"));
  await heldRow("Bread");
  // One receipt at a time: the bar names the last tick and has one Ångra; both rows are still held in their places.
  await waitFor(() =>
    expect(receiptText()).toBe(`${shoppingEn.bought}: Bread`),
  );
  expect(
    document.querySelectorAll(".shopping-group .shopping-held-item"),
  ).toHaveLength(2);
  expect(
    document.querySelectorAll(".sk-receipt .sk-receipt__action"),
  ).toHaveLength(1);
  // Both rows are still held, so "Bought" does not count them yet.
  expect(
    screen.queryByRole("button", { name: /^Bought/ }),
  ).not.toBeInTheDocument();

  await user.click(await findReceiptUndo("Undo"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(3));
  const [back] = vi.mocked(transport.purchase).mock.calls[2]!;
  expect(back).toMatchObject({ id: bread.id, purchased: true, version: 2 });
  expect(stored.get(bread.id)).toBe(false);
  expect(stored.get(milk.id)).toBe(true);
  // The bar is empty again, so the held row of Milk goes where it belongs (the fold) and Bread is simply open.
  await waitFor(() => expect(receiptNow()).toBeNull());
  await waitFor(() =>
    expect(document.querySelector(".shopping-held-item")).toBeNull(),
  );
  expect(
    elementWithText(shoppingEn.boughtCount(1), "button"),
  ).toBeInTheDocument();
});

it("a run of two ticks holds both rows until the bar is empty, then releases them together", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { transport, bread } = twoRowServer();
  const user = userEvent.setup({
    advanceTimers: (ms) => {
      if (vi.isFakeTimers()) vi.advanceTimersByTime(ms);
    },
  });
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk, bread])}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(ring("Milk"));
  await heldRow("Milk");
  // Milk's receipt runs for a while, then Bread is ticked: the new receipt replaces it and its time starts over.
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 2_000);
  });
  await waitFor(() => expect(ring("Bread")).toBeEnabled());
  await user.click(ring("Bread"));
  await heldRow("Bread");
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 2_000);
  });
  // Longer than the first receipt's own time has passed, yet the first row has not moved under the thumb.
  expect(receiptNow()).not.toBeNull();
  expect(
    document.querySelectorAll(".shopping-group .shopping-held-item"),
  ).toHaveLength(2);
  expect(
    screen.queryByRole("button", { name: /^Bought/ }),
  ).not.toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(2_500);
  });
  // The bar ran out: both rows leave their places at the same moment and are counted under Köpta.
  expect(receiptNow()).toBeNull();
  expect(document.querySelector(".shopping-held-item")).toBeNull();
  expect(
    elementWithText(shoppingEn.boughtCount(2), "button"),
  ).toBeInTheDocument();
  // Nothing but the two ticks was written.
  expect(transport.purchase).toHaveBeenCalledTimes(2);
});

it("a list where no item has a store draws no store heading at all (ua-14)", () => {
  const plain = detail([
    lamp,
    { ...lamp, id: `${lamp.id.slice(0, -1)}9`, name: "Bulb" },
  ]);
  render(
    <ShoppingView
      transport={adapter(plain)}
      labels={shoppingSv}
      initial={plain}
    />,
  );
  expect(screen.queryByRole("heading", { level: 3 })).toBeNull();
  expect(screen.getByText("Lamp")).toBeInTheDocument();
});

it("offers the host's settings in the list's ⋯ in place of Kontroll (ua-8)", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  render(
    <ShoppingView
      transport={adapter(detail([milk]))}
      labels={shoppingSv}
      initial={detail([milk])}
      fullscreen
      hostSettings={{ label: "Inställningar", onOpen }}
    />,
  );
  await user.click(
    screen.getAllByRole("button", { name: shoppingSv.moreActions })[0]!,
  );
  await user.click(
    await screen.findByRole("button", { name: "Inställningar" }),
  );
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(screen.queryByRole("button", { name: "Kontroll" })).toBeNull();
});
