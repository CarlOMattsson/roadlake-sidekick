import { act, render, screen, waitFor } from "@testing-library/react";
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
  store: "ICA MAXI 4",
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

/** An add whose answers the test gives by hand, one per call, so the typing can go on while a write is on its way. */
function slowAdd() {
  const answers: { resolve: () => void; reject: () => void }[] = [];
  const add = vi.fn(
    () =>
      new Promise<unknown>((resolve, reject) => {
        answers.push({
          resolve: () => resolve({}),
          reject: () => reject(new Error("network down")),
        });
      }),
  );
  return { add, answers };
}

function adapter(add: ShoppingTransport["add"]): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add,
    update: vi.fn(),
    purchase: vi.fn(),
  };
}

async function openField(
  user: ReturnType<typeof userEvent.setup>,
  fullscreen: boolean,
  transport: ShoppingTransport,
) {
  render(
    <ShoppingView
      transport={transport}
      labels={shoppingEn}
      initial={detail}
      fullscreen={fullscreen}
      store={fullscreen ? undefined : "Coop"}
    />,
  );
  await waitFor(() =>
    expect(document.querySelector(".shopping-loading")).toBeNull(),
  );
  await user.click(screen.getByRole("button", { name: shoppingEn.addItem }));
  return screen.getByRole("textbox", { name: shoppingEn.addItem });
}

describe.each([
  ["fullscreen", true],
  ["card", false],
])("fast typing in the add field (%s)", (_name, fullscreen) => {
  it("takes the sent text out at once, so the next item is typed into an empty field and sent after the first", async () => {
    const { add, answers } = slowAdd();
    const user = userEvent.setup();
    const transport = adapter(add);
    const field = await openField(user, fullscreen, transport);

    await user.type(field, "yoghurt 1 l{Enter}");
    // The server has not answered; the field is empty and open for the next item.
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    await user.type(field, "morötter 1 kg{Enter}");
    expect(field).toHaveValue("");
    await user.type(field, "basilika");
    expect(field).toHaveValue("basilika");

    await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
    const calls = add.mock.calls as unknown as unknown[][];
    expect(calls[0]).toEqual([
      list.id,
      [{ name: "Yoghurt", quantity: "1", unit: "l" }],
      expect.any(String),
      expect.anything(),
    ]);
    // The second write waits for the first; it is not lost and not merged into it.
    await act(async () => {
      answers[0]!.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(add).toHaveBeenCalledTimes(2));
    expect(calls[1]![1]).toEqual([
      { name: "Morötter", quantity: "1", unit: "kg" },
    ]);
    await act(async () => {
      answers[1]!.resolve();
      await Promise.resolve();
    });
    await waitFor(() => expect(add).toHaveBeenCalledTimes(2));
    expect(field).toHaveValue("basilika");
  });

  it("a refused add puts its text back instead of dropping it, and shows the failure", async () => {
    const { add, answers } = slowAdd();
    const user = userEvent.setup();
    const transport = adapter(add);
    const field = await openField(user, fullscreen, transport);

    await user.type(field, "yoghurt{Enter}");
    expect(field).toHaveValue("");
    await waitFor(() => expect(add).toHaveBeenCalledTimes(1));
    await act(async () => {
      answers[0]!.reject();
      await Promise.resolve();
    });
    expect(await screen.findByRole("alert")).toHaveTextContent(
      shoppingEn.saveFailed,
    );
    expect(field).toHaveValue("yoghurt");
  });
});
