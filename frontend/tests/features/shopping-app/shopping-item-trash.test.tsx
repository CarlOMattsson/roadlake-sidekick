import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import {
  afterAll,
  beforeAll,
  beforeEach,
  describe,
  expect,
  it,
  vi,
} from "vitest";
import { ShoppingRoom } from "@/features/shopping-app/room";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";
import {
  findReceiptUndo,
  receiptNow,
  receiptText,
} from "@tests/helpers/receipt-bar";

// Delete with Undo for one item: the change form's Delete moves the item to the trash (move_to_trash, kind
// "shopping_item"), the receipt bar offers Undo (restore_from_trash at the trash version), and a failure keeps the row.

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
    version: 3,
    ...over,
  };
}

const milk = item({ id: "019f0000-0000-7000-8000-0000000000a1", name: "Milk" });
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Eggs",
});
const full: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk, eggs],
};
const without: ShoppingDetail = { ...full, items: [eggs] };

function adapter(over: Partial<ShoppingTransport> = {}): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(full),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn(),
    purchase: vi.fn(),
    trashItem: vi.fn().mockResolvedValue({ version: 8 }),
    restoreItem: vi.fn().mockResolvedValue({}),
    ...over,
  };
}

async function open(
  transport: ShoppingTransport,
  labels = shoppingEn,
  fullscreen = true,
) {
  render(
    <ShoppingView
      transport={transport}
      labels={labels}
      initial={full}
      fullscreen={fullscreen}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
}

/** Opens the change form of an item: a tap on its row. */
async function openForm(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
) {
  await user.click(screen.getByText(name));
}

beforeEach(() => {
  localStorage.clear();
});

describe("deleting an item", () => {
  it("moves it to the trash at its version, takes the row away and shows a receipt in the bar with Undo", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await waitFor(() => expect(transport.trashItem).toHaveBeenCalledTimes(1));
    expect(transport.trashItem).toHaveBeenCalledWith(
      milk.id,
      milk.version,
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
    // The row is gone; the receipt is the bar's, not a row of the list.
    await waitFor(() => expect(receiptText()).toBe("Deleted: Milk"));
    expect(document.querySelector(".shopping-receipt")).toBeNull();
    expect(
      screen.queryByRole("button", { name: /^Mark Milk as/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Mark Eggs as/ })).toBeVisible();
    expect(await findReceiptUndo("Undo")).toHaveTextContent("Undo");
  });

  it("Undo restores the item with the trash version from the answer and shows the row again", async () => {
    const user = userEvent.setup();
    const get = vi.fn().mockResolvedValueOnce(without).mockResolvedValue(full);
    const transport = adapter({ get });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await user.click(await findReceiptUndo("Undo"));
    await waitFor(() => expect(transport.restoreItem).toHaveBeenCalledTimes(1));
    expect(transport.restoreItem).toHaveBeenCalledWith(
      milk.id,
      8,
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
    expect(
      await screen.findByRole("button", { name: /^Mark Milk as/ }),
    ).toBeVisible();
    await waitFor(() => expect(receiptNow()).toBeNull());
  });

  it("works in the inline card too, and is reached with the keyboard", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await open(transport, shoppingEn, false);
    // The row opens its change form with the keyboard as well.
    const row = screen.getByText("Milk").closest("button")!;
    row.focus();
    await user.keyboard("{Enter}");
    const button = screen.getByRole("button", { name: "Delete Milk" });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(transport.trashItem).toHaveBeenCalledTimes(1));
    await waitFor(() => expect(receiptText()).toBe("Deleted: Milk"));
  });

  it("says it in Swedish", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await open(transport, shoppingSv);
    await openForm(user, "Milk");
    const button = screen.getByRole("button", { name: "Ta bort Milk" });
    expect(button).toHaveTextContent("Ta bort");
    await user.click(button);
    await waitFor(() => expect(receiptText()).toBe("Borttagen: Milk"));
    expect(await findReceiptUndo("Ångra")).toHaveTextContent("Ångra");
  });

  it("keeps the row when the delete fails, and the retry reuses the idempotency key", async () => {
    const user = userEvent.setup();
    const trashItem = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({ version: 8 });
    const transport = adapter({
      trashItem,
      get: vi.fn().mockResolvedValue(full),
    });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await waitFor(() => expect(trashItem).toHaveBeenCalledTimes(1));
    expect(await screen.findByRole("alert")).toBeInTheDocument();
    expect(receiptNow()).toBeNull();
    // The change form is still open, so the item is still there to be deleted again.
    expect(screen.getByRole("button", { name: "Delete Milk" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: shoppingEn.retry }));
    await waitFor(() => expect(trashItem).toHaveBeenCalledTimes(2));
    expect(trashItem.mock.calls[1]![2]).toBe(trashItem.mock.calls[0]![2]);
    await waitFor(() => expect(receiptText()).toBe("Deleted: Milk"));
  });

  it("says so, and reads the list again, when the item was changed elsewhere", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      trashItem: vi.fn().mockRejectedValue({ code: "conflict" }),
    });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    // The item is still in the list, so the conflict is the row's own notice, not the view's box.
    expect(await screen.findByRole("alert")).toHaveTextContent(
      shoppingEn.conflict,
    );
    // The opening result was the first read, so this call is the re-read the conflict asks for.
    expect(transport.get).toHaveBeenCalledTimes(1);
    expect(receiptNow()).toBeNull();
  });

  it("names a failed Undo in the view's error box and offers Try again with the same key", async () => {
    const user = userEvent.setup();
    const restoreItem = vi
      .fn()
      .mockRejectedValueOnce(new Error("network"))
      .mockResolvedValue({});
    const transport = adapter({
      restoreItem,
      get: vi.fn().mockResolvedValueOnce(without).mockResolvedValue(full),
    });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await user.click(await findReceiptUndo("Undo"));
    // The row is gone from the list, so the box at the top of the view names the item that could not come back.
    const alert = await screen.findByRole("alert");
    expect(alert).toHaveClass("sk-message--error");
    expect(alert).toHaveTextContent(shoppingEn.itemRestoreFailed("Milk"));
    await waitFor(() => expect(receiptNow()).toBeNull());
    await user.click(
      within(alert).getByRole("button", { name: shoppingEn.retry }),
    );
    await waitFor(() => expect(restoreItem).toHaveBeenCalledTimes(2));
    expect(restoreItem.mock.calls[1]![2]).toBe(restoreItem.mock.calls[0]![2]);
    expect(restoreItem.mock.calls[1]![1]).toBe(8);
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("offers no delete when the transport has no trash tools", async () => {
    const user = userEvent.setup();
    await open(adapter({ trashItem: undefined, restoreItem: undefined }));
    await openForm(user, "Milk");
    expect(screen.getByRole("button", { name: shoppingEn.save })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /^Delete/ }),
    ).not.toBeInTheDocument();
  });
});

describe("the room's transport", () => {
  beforeAll(() => {
    document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  });
  afterAll(() => {
    document.head.innerHTML = "";
  });

  function room(supportsCall?: (name: string, args?: object) => boolean) {
    const call = vi.fn((name: string) => {
      if (name === "move_to_trash") return Promise.resolve({ version: 8 });
      if (name === "list_shopping_lists")
        return Promise.resolve({ lists: [list], next_offset: null });
      if (name === "get_shopping_list") return Promise.resolve(without);
      return Promise.resolve({});
    });
    render(
      <ShoppingRoom
        mode="full"
        transport={{
          call: call as never,
          requestDisplayMode: vi.fn() as never,
          updateModelContext: vi.fn() as never,
          ...(supportsCall ? { supportsCall } : {}),
        }}
        initial={full}
        resultId={1}
      />,
    );
    return call;
  }

  it("calls move_to_trash with the kind, the record, the version and a key", async () => {
    const user = userEvent.setup();
    const call = room();
    await user.click(await screen.findByText("Milk"));
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await waitFor(() =>
      expect(call).toHaveBeenCalledWith("move_to_trash", {
        kind: "shopping_item",
        record_id: milk.id,
        version: milk.version,
        idempotency_key: expect.stringMatching(/^[0-9a-f-]{36}$/) as string,
      }),
    );
  });

  it("shows no delete when the host answers no to the trash call", async () => {
    const user = userEvent.setup();
    const supportsCall = vi.fn(
      (name: string) =>
        name !== "move_to_trash" && name !== "restore_from_trash",
    );
    room(supportsCall);
    await user.click(await screen.findByText("Milk"));
    expect(screen.getByRole("button", { name: shoppingEn.save })).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /^Delete/ }),
    ).not.toBeInTheDocument();
    expect(supportsCall).toHaveBeenCalledWith("move_to_trash", {
      kind: "shopping_item",
    });
  });

  it("shows no delete when only one of the two tools is offered", async () => {
    const user = userEvent.setup();
    room((name) => name !== "restore_from_trash");
    await user.click(await screen.findByText("Milk"));
    expect(
      screen.queryByRole("button", { name: /^Delete/ }),
    ).not.toBeInTheDocument();
  });
});
