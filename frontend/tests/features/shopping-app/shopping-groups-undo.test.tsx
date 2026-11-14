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
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import { elementWithText } from "@tests/helpers/exact-text";

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

/**
 * The Ångra of a held row inside its shop group. The purchased list repeats a bought row, so a held row can
 * show its Ångra twice; the one in its group is the row's own place.
 */
async function groupUndo(name: string): Promise<HTMLElement> {
  return waitFor(() => {
    const undo = screen
      .getAllByRole("button", {
        name: shoppingEn.undoPurchaseNamed(name, true),
      })
      .find((button) => button.closest(".shopping-group"));
    if (!undo) throw new Error(`no Undo for ${name} in its group`);
    return undo;
  });
}

function groupOf(undo: HTMLElement): HTMLElement {
  return undo.closest("section.shopping-group")!;
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
  expect(within(group).getByText(/^Lamp ·/)).toBeInTheDocument();
  // The item without a store is not listed under a store heading.
  expect(within(group).queryByText(/^Milk ·/)).not.toBeInTheDocument();
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
  expect(within(section).queryByText(/^Eggs ·/)).toBeNull();
  fireEvent.click(fold);
  expect(fold).toHaveAttribute("aria-expanded", "true");
  expect(within(section).getByText(/^Eggs ·/)).toBeVisible();
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

it("ticking an item holds the row in its place as 'Bought · Undo'; Undo marks it open again", async () => {
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  const undoButton = await groupUndo("Milk");
  // The row stays where it was. In the inline list its status line says "Bought" and Undo is a tonal button in the
  // toolbar, where Edit stood. There is no notice any more.
  const row = undoButton.closest("li")!;
  expect(row).toHaveClass("shopping-held-item");
  expect(undoButton).toHaveClass("sk-btn--secondary", "sk-btn--compact");
  expect(undoButton.closest(".shopping-toolbar")).not.toBeNull();
  expect(row.querySelector(".shopping-status")).toHaveTextContent(
    shoppingEn.bought,
  );
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
  await waitFor(() =>
    expect(
      screen.queryAllByRole("button", {
        name: /^Undo (not )?bought /,
      }),
    ).toHaveLength(0),
  );
});

it("a refused Undo shows Try again in its row, and Try again repeats the same write with its key", async () => {
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox"));
  const undoButton = await groupUndo("Milk");
  await waitFor(() => expect(undoButton).toBeEnabled());
  await user.click(undoButton);
  const alert = await within(groupOf(undoButton)).findByRole("alert");
  expect(alert).toHaveTextContent(shoppingEn.markFailed("Milk", false));
  await user.click(
    within(groupOf(undoButton)).getByRole("button", {
      name: shoppingEn.retry,
    }),
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  const undoButton = await groupUndo("Milk");
  await waitFor(() => expect(undoButton).toBeEnabled());
  return { transport, user, rerender };
}

it("Undo is still offered 9 s after the purchase and sends the item back", async () => {
  vi.useFakeTimers({ shouldAdvanceTime: true });
  const { transport, user } = await buyMilk();
  act(() => {
    vi.advanceTimersByTime(9_000);
  });
  const undoButton = await groupUndo("Milk");
  await user.click(undoButton);
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(2));
  const [undone] = vi.mocked(transport.purchase).mock.calls[1]!;
  expect(undone).toMatchObject({ id: milk.id, purchased: true, version: 2 });
});

it("a re-render of the list during the Undo window keeps the Ångra of the held row", async () => {
  const { transport, user, rerender } = await buyMilk();
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: shoppingEn.refresh }),
    ).toBeEnabled(),
  );
  const readsBefore = vi.mocked(transport.get).mock.calls.length;
  await user.click(screen.getByRole("button", { name: shoppingEn.refresh }));
  await waitFor(() =>
    expect(vi.mocked(transport.get).mock.calls.length).toBeGreaterThan(
      readsBefore,
    ),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: shoppingEn.refresh }),
    ).toBeEnabled(),
  );
  rerender(
    <ShoppingView
      transport={transport}
      labels={{ ...shoppingEn }}
      initial={detail([milk])}
    />,
  );
  const undoButton = await groupUndo("Milk");
  expect(undoButton).toBeEnabled();
  expect(
    undoButton.closest("li")!.querySelector(".shopping-status"),
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox"));
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(
    screen.queryAllByRole("button", {
      name: /^Undo (not )?bought /,
    }),
  ).toHaveLength(0);
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox", { name: /^Milk/ }));
  const undo = await groupUndo("Milk");
  const row = undo.closest("li")!;
  expect(row).toHaveClass("shopping-held-item");
  // The bought row still stands between Bread and Pasta in the ICA MAXI 4 group.
  expect(row.previousElementSibling).toHaveTextContent(/^Bread ·/);
  expect(row.nextElementSibling).toHaveTextContent(/^Pasta ·/);
  // The group heading carries no count: it is the store's name alone.
  expect(groupOf(undo).querySelector("h3")?.textContent).toBe(milk.store);
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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox", { name: /^Milk/ }));
  const undo = await groupUndo("Milk");
  const group = groupOf(undo);
  expect(group.querySelector("h3")?.textContent).toBe(milk.store);
  expect(group.querySelectorAll("li")).toHaveLength(1);
  // The No store group follows the held row's group, as before the purchase.
  expect(group.nextElementSibling?.querySelector("h3")).toHaveTextContent(
    shoppingEn.otherStore,
  );
});

it("two purchases hold two rows, each with its own Ångra; each Ångra buys back only its row", async () => {
  const bread = item({
    id: "019f0000-0000-7000-8000-0000000000a4",
    name: "Bread",
  });
  // A small server: the purchase flips the stored flag, and the reads show what is stored.
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
  const user = userEvent.setup();
  const { container } = render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail([milk, bread])}
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  await user.click(screen.getByRole("checkbox", { name: /^Milk/ }));
  await groupUndo("Milk");
  await waitFor(() =>
    expect(screen.getByRole("checkbox", { name: /^Bread/ })).toBeEnabled(),
  );
  await user.click(screen.getByRole("checkbox", { name: /^Bread/ }));
  await groupUndo("Bread");
  expect(
    container.querySelectorAll(".shopping-group .shopping-undo"),
  ).toHaveLength(2);
  // Both rows are still held with their Ångra, so "Bought" does not count them yet.
  expect(
    screen.queryByRole("button", { name: /^Bought/ }),
  ).not.toBeInTheDocument();

  await user.click(await groupUndo("Bread"));
  await waitFor(() =>
    expect(
      container.querySelectorAll(".shopping-group .shopping-undo"),
    ).toHaveLength(1),
  );
  expect(stored.get(bread.id)).toBe(false);
  expect(stored.get(milk.id)).toBe(true);
  expect(await groupUndo("Milk")).toBeInTheDocument();
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
  expect(screen.getByText(/^Lamp ·/)).toBeInTheDocument();
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
