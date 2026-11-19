import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type { ShoppingLabels } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// Quick changes of an open row in the store view: the amount up or down by one (one write for taps that follow each
// other) and a move to another list from the row's menu, with a receipt and Undo. The compact card has neither.
// Simulated events in jsdom, not a real touch device.

const list = {
  id: "019f0000-0000-7000-8000-000000000001",
  name: "Weekly shopping",
  version: 1,
  archived: false,
  created_at: "2026-10-24T12:00:00Z",
  updated_at: "2026-10-24T12:00:00Z",
};
const weekend = {
  ...list,
  id: "019f0000-0000-7000-8000-000000000002",
  name: "Weekend",
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
    store: null,
    target_date: null,
    created_at: "2026-10-24T12:00:00Z",
    updated_at: "2026-10-24T12:00:00Z",
    version: 3,
    ...over,
  };
}

const milk = item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" });
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Eggs",
  quantity: "1",
  unit: null,
});
const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk, eggs],
};

/** The server's answer to an update: the item with the written fields and the next version. */
const stored: ShoppingTransport["update"] = (row, input) =>
  Promise.resolve({
    item: {
      ...row,
      name: input.name ?? row.name,
      quantity: String(input.quantity),
      list_id: input.list_id ?? row.list_id,
      version: row.version + 1,
    },
  });

function adapter(over: Partial<ShoppingTransport> = {}): ShoppingTransport {
  return {
    lists: vi
      .fn()
      .mockResolvedValue({ lists: [list, weekend], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(stored),
    purchase: vi.fn(),
    ...over,
  };
}

type OpenOptions = {
  labels?: ShoppingLabels;
  compact?: boolean;
  fullscreen?: boolean;
  initial?: ShoppingDetail;
};

async function mount(transport: ShoppingTransport, options: OpenOptions = {}) {
  const view = render(
    <ShoppingView
      transport={transport}
      labels={options.labels ?? shoppingEn}
      initial={options.initial ?? detail}
      fullscreen={options.fullscreen ?? true}
      compact={options.compact}
    />,
  );
  await waitFor(() =>
    expect(screen.queryByText(shoppingEn.loading)).not.toBeInTheDocument(),
  );
  return { transport, unmount: view.unmount };
}

async function open(transport = adapter(), options: OpenOptions = {}) {
  return (await mount(transport, options)).transport;
}

const more = (name: string, labels = shoppingEn) =>
  screen.getByRole("button", { name: labels.rowMenu(name) });
const plus = (name: string, labels = shoppingEn) =>
  screen.getByRole("button", { name: labels.increaseQuantity(name) });
const minus = (name: string, labels = shoppingEn) =>
  screen.getByRole("button", { name: labels.decreaseQuantity(name) });
const amountOf = (row: HTMLElement) =>
  row.querySelector(".shopping-store-qty")?.textContent;
const rowOf = (name: string) =>
  screen.getByText(name, { selector: ".shopping-store-name" }).closest("li")!;

describe("the amount steps", () => {
  it("+ draws the new amount at once and writes it once the taps have stopped", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await user.click(plus("Milk"));
    expect(amountOf(rowOf("Milk"))).toBe("3 l");
    expect(transport.update).not.toHaveBeenCalled();
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![0]).toMatchObject({
      id: milk.id,
      version: 3,
    });
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "3",
    });
    await waitFor(() => expect(amountOf(rowOf("Milk"))).toBe("3 l"));
  });

  it("fast repeated taps are one write of the final amount", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await user.click(plus("Milk"));
    await user.click(plus("Milk"));
    await user.click(plus("Milk"));
    await user.click(minus("Milk"));
    expect(amountOf(rowOf("Milk"))).toBe("4 l");
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "4",
    });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).toHaveBeenCalledTimes(1);
  });

  it("a later change is written against the version the earlier reply gave", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await user.click(plus("Milk"));
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(amountOf(rowOf("Milk"))).toBe("3 l"));
    await user.click(plus("Milk"));
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(2));
    expect(vi.mocked(transport.update).mock.calls[1]![0]).toMatchObject({
      version: 4,
    });
    expect(vi.mocked(transport.update).mock.calls[1]![1]).toEqual({
      name: "Milk",
      quantity: "4",
    });
  });

  it("− at 1 changes nothing, writes nothing and keeps the focus on the button", async () => {
    const user = userEvent.setup();
    const transport = await open();
    const down = minus("Eggs");
    expect(down).toHaveAttribute("aria-disabled", "true");
    await user.click(down);
    expect(down).toHaveFocus();
    expect(minus("Milk")).not.toHaveAttribute("aria-disabled");
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).not.toHaveBeenCalled();
    expect(amountOf(rowOf("Eggs"))).toBeUndefined();
  });

  it("− takes one off and stops at 1", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await user.click(minus("Milk"));
    await user.click(minus("Milk"));
    expect(amountOf(rowOf("Milk"))).toBe("1 l");
    expect(minus("Milk")).toHaveAttribute("aria-disabled", "true");
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "1",
    });
  });

  it("a refused write puts the amount back and offers Try again with the same key", async () => {
    const user = userEvent.setup();
    const update = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementation(stored);
    const transport = await open(adapter({ update }));
    await user.click(plus("Milk"));
    const alert = await screen.findByRole("alert");
    // The notice does not claim that a purchase failed.
    expect(alert).toHaveTextContent(shoppingEn.failed);
    expect(amountOf(rowOf("Milk"))).toBe("2 l");
    await user.click(
      within(alert).getByRole("button", { name: shoppingEn.retry }),
    );
    await waitFor(() => expect(amountOf(rowOf("Milk"))).toBe("3 l"));
    expect(transport.update).toHaveBeenCalledTimes(2);
    const [first, second] = vi.mocked(transport.update).mock.calls;
    expect(second![2]).toBe(first![2]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("a stale version reads the list again and says the row changed elsewhere", async () => {
    const user = userEvent.setup();
    const update = vi.fn().mockRejectedValue({ code: "conflict" });
    const transport = await open(adapter({ update }));
    const reads = vi.mocked(transport.get).mock.calls.length;
    await user.click(plus("Milk"));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      shoppingEn.conflict,
    );
    expect(vi.mocked(transport.get).mock.calls.length).toBeGreaterThan(reads);
    expect(amountOf(rowOf("Milk"))).toBe("2 l");
  });

  it("names the buttons for the item, in Swedish too", async () => {
    await open(adapter(), { labels: shoppingSv });
    expect(plus("Milk", shoppingSv)).toHaveAccessibleName("Öka antal Milk");
    expect(minus("Milk", shoppingSv)).toHaveAccessibleName("Minska antal Milk");
    expect(more("Milk", shoppingSv)).toHaveAccessibleName("Fler val för Milk");
  });

  it("makes each button a 44 px target", async () => {
    await open();
    for (const button of [plus("Milk"), minus("Milk"), more("Milk")])
      expect(button).toHaveClass("sk-iconbtn");
  });
});

describe("an amount that is still settling when the view goes away", () => {
  it("is written once when the view closes within the delay", async () => {
    const user = userEvent.setup();
    const { transport, unmount } = await mount(adapter());
    await user.click(plus("Milk"));
    unmount();
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![0]).toMatchObject({
      id: milk.id,
      version: 3,
    });
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "3",
    });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).toHaveBeenCalledTimes(1);
  });

  it("is written against its own list when another list is chosen within the delay", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValue({ ...detail, shopping_list: weekend }),
    });
    await open(transport);
    await user.click(plus("Milk"));
    await user.click(
      screen.getByRole("button", {
        name: `Tillbaka till ${shoppingEn.backToLists}`,
      }),
    );
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![0]).toMatchObject({
      id: milk.id,
      list_id: list.id,
      version: 3,
    });
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "3",
    });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).toHaveBeenCalledTimes(1);
  });

  it("is not written twice when the delay had already passed", async () => {
    const user = userEvent.setup();
    const { transport, unmount } = await mount(adapter());
    await user.click(plus("Milk"));
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    unmount();
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).toHaveBeenCalledTimes(1);
  });

  it("does not throw or warn when the write is refused after the view is gone", async () => {
    const user = userEvent.setup();
    const errors = vi.spyOn(console, "error").mockImplementation(() => {});
    const update = vi.fn().mockRejectedValue(new Error("offline"));
    const { transport, unmount } = await mount(adapter({ update }));
    await user.click(plus("Milk"));
    unmount();
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    await new Promise((resolve) => setTimeout(resolve, 50));
    expect(errors).not.toHaveBeenCalled();
    errors.mockRestore();
  });
});

describe("move to another list", () => {
  async function chooseMove(user: ReturnType<typeof userEvent.setup>) {
    await user.click(more("Milk"));
    await user.click(
      screen.getByRole("button", { name: shoppingEn.moveToList("Weekend") }),
    );
  }

  it("lists the other lists in the row's menu, and not the item's own", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(more("Milk"));
    expect(
      screen.getByRole("button", { name: "Move to Weekend" }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Move to Weekly shopping" }),
    ).toBeNull();
    expect(more("Milk")).toHaveAttribute("aria-expanded", "true");
  });

  it("Escape closes the menu and gives the focus back to ⋯", async () => {
    const user = userEvent.setup();
    await open();
    await user.click(more("Milk"));
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: "Move to Weekend" }),
    ).toBeNull();
    expect(more("Milk")).toHaveFocus();
  });

  it("moves the item with update_shopping_item's list_id, takes it out of the list and says so", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await chooseMove(user);
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![0]).toMatchObject({
      id: milk.id,
      version: 3,
    });
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "2",
      list_id: weekend.id,
    });
    expect(
      screen.queryByText("Milk", { selector: ".shopping-store-name" }),
    ).toBeNull();
    expect(
      await screen.findByText("Moved to Weekend: Milk"),
    ).toBeInTheDocument();
    // A move is not a read: the list is not read again.
    expect(transport.get).not.toHaveBeenCalled();
  });

  it("Undo moves the item back with the version of the move and the row returns", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await chooseMove(user);
    const undo = await screen.findByRole("button", {
      name: shoppingEn.undoMoveNamed("Milk"),
    });
    await waitFor(() => expect(undo).toBeEnabled());
    await user.click(undo);
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(2));
    expect(vi.mocked(transport.update).mock.calls[1]![0]).toMatchObject({
      version: 4,
    });
    expect(vi.mocked(transport.update).mock.calls[1]![1]).toEqual({
      name: "Milk",
      quantity: "2",
      list_id: list.id,
    });
    await waitFor(() =>
      expect(
        screen.getByText("Milk", { selector: ".shopping-store-name" }),
      ).toBeInTheDocument(),
    );
    expect(screen.queryByText("Moved to Weekend: Milk")).toBeNull();
  });

  it("an amount that was still settling goes with the move in one write", async () => {
    const user = userEvent.setup();
    const transport = await open();
    await user.click(plus("Milk"));
    await chooseMove(user);
    await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
    expect(vi.mocked(transport.update).mock.calls[0]![1]).toEqual({
      name: "Milk",
      quantity: "3",
      list_id: weekend.id,
    });
    await new Promise((resolve) => setTimeout(resolve, 600));
    expect(transport.update).toHaveBeenCalledTimes(1);
  });

  it("a refused move brings the row back where it stood and says so", async () => {
    const user = userEvent.setup();
    const update = vi.fn().mockRejectedValue(new Error("offline"));
    await open(adapter({ update }));
    await chooseMove(user);
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    const names = screen
      .getAllByText(/^(Milk|Eggs)$/, { selector: ".shopping-store-name" })
      .map((node) => node.textContent);
    expect(names).toEqual(["Milk", "Eggs"]);
    expect(screen.queryByText("Moved to Weekend: Milk")).toBeNull();
  });

  it("offers no menu when there is no other list", async () => {
    await open(
      adapter({
        lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
      }),
    );
    expect(plus("Milk")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: shoppingEn.rowMenu("Milk") }),
    ).toBeNull();
  });
});

describe("where the quick changes are not", () => {
  it("the compact inline card has neither the steps nor the menu", async () => {
    await open(adapter(), { compact: true, fullscreen: false });
    await screen.findByText(/Milk/);
    expect(screen.queryByRole("button", { name: /quantity/i })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /More options for/ }),
    ).toBeNull();
    expect(document.querySelector(".shopping-quick")).toBeNull();
  });

  it("an archived list has none", async () => {
    await open(adapter(), {
      initial: { ...detail, shopping_list: { ...list, archived: true } },
    });
    await screen.findByText("Milk", { selector: ".shopping-store-name" });
    expect(document.querySelector(".shopping-quick")).toBeNull();
  });

  it("a bought row has none", async () => {
    const bread = item({
      id: "019f0000-0000-7000-8000-0000000000a3",
      name: "Bread",
      purchased: true,
      purchased_at: "2026-10-24T12:00:00Z",
    });
    const user = userEvent.setup();
    await open(adapter(), { initial: { ...detail, items: [milk, bread] } });
    await user.click(await screen.findByText("Bought"));
    expect(
      screen.queryByRole("button", {
        name: shoppingEn.increaseQuantity("Bread"),
      }),
    ).toBeNull();
    expect(plus("Milk")).toBeInTheDocument();
  });
});
