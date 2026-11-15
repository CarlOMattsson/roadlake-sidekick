import { render, screen, waitFor } from "@testing-library/react";
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

// Delete with Undo for one item: the change form's Delete moves the item to the trash (move_to_trash, kind
// "shopping_item"), a receipt row offers Undo (restore_from_trash at the trash version), and a failure keeps the row.

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
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
}

/** Opens the change form of an item: the store view's row, or the list view's Edit button. */
async function openForm(
  user: ReturnType<typeof userEvent.setup>,
  name: string,
  labels = shoppingEn,
) {
  const edit = screen.queryByRole("button", { name: labels.edit });
  if (edit) await user.click(edit);
  else await user.click(screen.getByText(name));
}

beforeEach(() => {
  localStorage.clear();
});

describe("deleting an item", () => {
  it("moves it to the trash at its version, takes the row away and shows a receipt with Undo", async () => {
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
    // The row is gone, the receipt stands in the list.
    expect(await screen.findByText("Deleted: Milk")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /^Mark Milk as/ }),
    ).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /^Mark Eggs as/ })).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Undo deleting Milk" }),
    ).toHaveTextContent("Undo");
  });

  it("Undo restores the item with the trash version from the answer and shows the row again", async () => {
    const user = userEvent.setup();
    const get = vi.fn().mockResolvedValueOnce(without).mockResolvedValue(full);
    const transport = adapter({ get });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    await user.click(
      await screen.findByRole("button", { name: "Undo deleting Milk" }),
    );
    await waitFor(() => expect(transport.restoreItem).toHaveBeenCalledTimes(1));
    expect(transport.restoreItem).toHaveBeenCalledWith(
      milk.id,
      8,
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
    expect(
      await screen.findByRole("button", { name: /^Mark Milk as/ }),
    ).toBeVisible();
    expect(screen.queryByText("Deleted: Milk")).not.toBeInTheDocument();
  });

  it("works in the list view too, and is reached with the keyboard", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await open(transport, shoppingEn, false);
    await user.click(
      screen.getAllByRole("button", { name: shoppingEn.edit })[0]!,
    );
    const button = screen.getByRole("button", { name: "Delete Milk" });
    button.focus();
    expect(button).toHaveFocus();
    await user.keyboard("{Enter}");
    await waitFor(() => expect(transport.trashItem).toHaveBeenCalledTimes(1));
    expect(await screen.findByText("Deleted: Milk")).toBeInTheDocument();
  });

  it("says it in Swedish", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      get: vi.fn().mockResolvedValueOnce(without),
    });
    await open(transport, shoppingSv);
    await openForm(user, "Milk", shoppingSv);
    const button = screen.getByRole("button", { name: "Ta bort Milk" });
    expect(button).toHaveTextContent("Ta bort");
    await user.click(button);
    expect(await screen.findByText("Borttagen: Milk")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Ångra borttagning av Milk" }),
    ).toHaveTextContent("Ångra");
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
    expect(screen.queryByText("Deleted: Milk")).not.toBeInTheDocument();
    // The change form is still open, so the item is still there to be deleted again.
    expect(screen.getByRole("button", { name: "Delete Milk" })).toBeVisible();
    await user.click(screen.getByRole("button", { name: shoppingEn.retry }));
    await waitFor(() => expect(trashItem).toHaveBeenCalledTimes(2));
    expect(trashItem.mock.calls[1]![2]).toBe(trashItem.mock.calls[0]![2]);
    expect(await screen.findByText("Deleted: Milk")).toBeInTheDocument();
  });

  it("says so, and reads the list again, when the item was changed elsewhere", async () => {
    const user = userEvent.setup();
    const transport = adapter({
      trashItem: vi.fn().mockRejectedValue({ code: "conflict" }),
    });
    await open(transport);
    await openForm(user, "Milk");
    await user.click(screen.getByRole("button", { name: "Delete Milk" }));
    expect(await screen.findByRole("alert")).toHaveTextContent(
      shoppingEn.conflict,
    );
    // The opening result was the first read, so this call is the re-read the conflict asks for.
    expect(transport.get).toHaveBeenCalledTimes(1);
    expect(screen.queryByText("Deleted: Milk")).not.toBeInTheDocument();
  });

  it("names a failed Undo in its receipt row and offers Try again", async () => {
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
    await user.click(
      await screen.findByRole("button", { name: "Undo deleting Milk" }),
    );
    expect(
      await screen.findByText(shoppingEn.itemRestoreFailed("Milk")),
    ).toBeInTheDocument();
    expect(screen.getByText("Deleted: Milk")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: shoppingEn.retry }));
    await waitFor(() => expect(restoreItem).toHaveBeenCalledTimes(2));
    expect(restoreItem.mock.calls[1]![2]).toBe(restoreItem.mock.calls[0]![2]);
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
