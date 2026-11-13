import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, it, vi } from "vitest";
import { ShoppingView } from "@/features/shopping-app/shopping-view";
import { shoppingEn, shoppingSv } from "@/features/shopping-app/labels";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingTransport,
} from "@/features/shopping-app/transport";

// In the store view the ring (a button) ticks the item; a tap on the rest of the row, a long
// press (contextmenu) and Shift+F10 open the item's change form under the row. Simulated events, not a real touch device.
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
const eggs = item({
  id: "019f0000-0000-7000-8000-0000000000a2",
  name: "Eggs",
});
const detail: ShoppingDetail = {
  shopping_list: list,
  evaluated_on: "2026-10-24",
  next_offset: null,
  items: [milk, eggs],
};

function adapter(): ShoppingTransport {
  return {
    lists: vi.fn().mockResolvedValue({ lists: [list], next_offset: null }),
    get: vi.fn().mockResolvedValue(detail),
    contacts: vi.fn().mockResolvedValue({ contacts: [] }),
    create: vi.fn(),
    rename: vi.fn(),
    add: vi.fn(),
    update: vi.fn().mockResolvedValue({ ...milk, version: 2 }),
    purchase: vi.fn().mockResolvedValue({}),
  };
}

async function open(labels = shoppingEn, transport = adapter()) {
  render(
    <ShoppingView
      transport={transport}
      labels={labels}
      initial={detail}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  return transport;
}

const ring = (name: string) =>
  screen.getByRole("button", { name: new RegExp(`^Mark ${name} as`) });
const box = (name: string) =>
  screen.getByRole("button", { name: new RegExp(`^${name}`) });
const editorLegend = (name: string) =>
  screen.queryByText(`${shoppingEn.edit}: ${name}`);

beforeEach(() => {
  localStorage.clear();
  delete document.documentElement.dataset.shoppingHold;
});

it("the row is two sibling buttons, never nested: the ring and the row", async () => {
  await open();
  const line = box("Milk").parentElement!;
  expect(line).toHaveClass("shopping-store-line");
  expect(ring("Milk").parentElement).toBe(line);
  expect(ring("Milk")).toHaveClass("shopping-ring");
  expect(box("Milk")).toHaveClass("shopping-store-row");
  expect(line.querySelector("button button, label, input")).toBeNull();
});

it("a click on the ring ticks the item and opens no form", async () => {
  const user = userEvent.setup();
  const transport = await open();
  await user.click(ring("Milk"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
  expect(vi.mocked(transport.purchase).mock.calls[0]![0]).toMatchObject({
    id: milk.id,
    purchased: false,
  });
  expect(editorLegend("Milk")).not.toBeInTheDocument();
});

it("a click on the rest of the row opens the change form and does not tick the item", async () => {
  const user = userEvent.setup();
  const transport = await open();
  await user.click(screen.getByText("Milk"));
  expect(editorLegend("Milk")).toBeInTheDocument();
  expect(transport.purchase).not.toHaveBeenCalled();
  // The form stands inside the item's own list entry, under the row; a tap leaves the focus where it was.
  expect(editorLegend("Milk")!.closest("li")).toBe(box("Milk").closest("li"));
  expect(screen.getByLabelText(shoppingEn.name)).not.toHaveFocus();
});

it("a long press or right click opens the same form without ticking, and the click after it is harmless", async () => {
  const transport = await open();
  const row = screen.getByText("Milk");
  fireEvent.pointerDown(row);
  fireEvent.contextMenu(row);
  expect(editorLegend("Milk")).toBeInTheDocument();
  // The click that follows the lifted finger lands on the same row: still the form, never a purchase.
  fireEvent.click(row);
  expect(editorLegend("Milk")).toBeInTheDocument();
  expect(transport.purchase).not.toHaveBeenCalled();
  expect(ring("Milk")).toHaveAccessibleName(/as bought/);
});

it("the ring still ticks after a form was opened", async () => {
  const user = userEvent.setup();
  const transport = await open();
  fireEvent.contextMenu(screen.getByText("Milk"));
  await user.click(ring("Eggs"));
  await waitFor(() => expect(transport.purchase).toHaveBeenCalledTimes(1));
});

it("the ring says what a tap does, in both languages, and flips once the item is bought", async () => {
  const user = userEvent.setup();
  // The purchase stays unanswered, so the row shows the optimistic state.
  await open(shoppingEn, {
    ...adapter(),
    purchase: vi.fn(() => new Promise<never>(() => undefined)),
  });
  expect(ring("Milk")).toHaveAccessibleName("Mark Milk as bought");
  await user.click(ring("Milk"));
  // (The bought item stands in its place and, once the "Bought" fold is open, once more under it.)
  expect(
    screen.getAllByRole("button", { name: "Mark Milk as not bought" }),
  ).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: /^Bought/ }));
  expect(
    screen.getAllByRole("button", { name: "Mark Milk as not bought" }),
  ).toHaveLength(2);
  expect(shoppingSv.markBought("Mjölk")).toBe("Markera Mjölk som köpt");
  expect(shoppingSv.markOpen("Mjölk")).toBe("Markera Mjölk som ej köpt");
});

it("Shift+F10 on the row opens the form, and so does the menu key", async () => {
  await open();
  const row = box("Milk");
  row.focus();
  fireEvent.keyDown(row, { key: "F10", shiftKey: true });
  expect(editorLegend("Milk")).toBeInTheDocument();
  expect(row).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
  expect(row).toHaveAttribute("aria-description", shoppingEn.holdTip);
  fireEvent.keyDown(box("Eggs"), { key: "ContextMenu" });
  // At most one form is open: the second row's replaces the first.
  expect(editorLegend("Eggs")).toBeInTheDocument();
  expect(editorLegend("Milk")).not.toBeInTheDocument();
});

it("Enter on the row opens the form with the focus on its first field", async () => {
  const user = userEvent.setup();
  await open();
  box("Milk").focus();
  await user.keyboard("{Enter}");
  expect(editorLegend("Milk")).toBeInTheDocument();
  await waitFor(() =>
    expect(screen.getByLabelText(shoppingEn.name)).toHaveFocus(),
  );
});

it("Escape closes the form and gives the focus back to the row", async () => {
  await open();
  const row = box("Milk");
  row.focus();
  fireEvent.keyDown(row, { key: "F10", shiftKey: true });
  const name = screen.getByLabelText(shoppingEn.name);
  name.focus();
  fireEvent.keyDown(name, { key: "Escape" });
  expect(editorLegend("Milk")).not.toBeInTheDocument();
  expect(box("Milk")).toHaveFocus();
});

it("Cancel and Save close the form with the focus on the row, Save through the same update write", async () => {
  const user = userEvent.setup();
  const transport = await open();
  fireEvent.contextMenu(screen.getByText("Milk"));
  await user.click(screen.getByRole("button", { name: shoppingEn.cancel }));
  expect(editorLegend("Milk")).not.toBeInTheDocument();
  expect(box("Milk")).toHaveFocus();
  fireEvent.contextMenu(screen.getByText("Milk"));
  await user.click(screen.getByRole("button", { name: shoppingEn.save }));
  await waitFor(() => expect(transport.update).toHaveBeenCalledTimes(1));
  expect(vi.mocked(transport.update).mock.calls[0]![0]).toMatchObject({
    id: milk.id,
  });
  await waitFor(() => expect(editorLegend("Milk")).not.toBeInTheDocument());
  expect(box("Milk")).toHaveFocus();
});

it("an archived list disables both the ring and the row", async () => {
  render(
    <ShoppingView
      transport={adapter()}
      labels={shoppingEn}
      initial={{ ...detail, shopping_list: { ...list, archived: true } }}
      fullscreen
    />,
  );
  await waitFor(() =>
    expect(screen.queryByRole("status")).not.toBeInTheDocument(),
  );
  expect(ring("Milk")).toBeDisabled();
  expect(box("Milk")).toBeDisabled();
  // A row that cannot be opened has no ›, and is marked so the stylesheet reads it without dimming it.
  expect(box("Milk").querySelector(".shopping-chevron")).toBeNull();
  expect(box("Milk").closest("li")).toHaveClass(
    "shopping-store-item--archived",
  );
  fireEvent.contextMenu(screen.getByText("Milk"));
  expect(editorLegend("Milk")).not.toBeInTheDocument();
});

it("the tip stands after the last shop until the first form is opened, then is gone for good", async () => {
  await open();
  const tip = screen.getByText(shoppingEn.holdTip);
  expect(tip).toBeInTheDocument();
  // It follows the last shop's list.
  const groups = document.querySelectorAll(".shopping-group");
  expect(
    groups[groups.length - 1]!.compareDocumentPosition(tip) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  fireEvent.contextMenu(screen.getByText("Milk"));
  expect(screen.queryByText(shoppingEn.holdTip)).not.toBeInTheDocument();
  expect(localStorage["sidekick.shoppingHoldUsed"]).toBe("1");
});

it("Shift+F10 also retires the tip", async () => {
  await open();
  fireEvent.keyDown(box("Milk"), { key: "F10", shiftKey: true });
  expect(screen.queryByText(shoppingEn.holdTip)).not.toBeInTheDocument();
});

// One once-only tip. The tip names the ring, so the first tap on a ring retires it too, and the
// answer is kept in the frame's storage (with the document's dataset as the session's reserve).
it("the first tap on a ring retires the tip for good, in storage and in the document", async () => {
  const user = userEvent.setup();
  await open();
  expect(screen.getByText(shoppingEn.holdTip)).toBeInTheDocument();
  expect(localStorage["sidekick.shoppingHoldUsed"]).toBeUndefined();
  await user.click(ring("Milk"));
  expect(screen.queryByText(shoppingEn.holdTip)).not.toBeInTheDocument();
  expect(localStorage["sidekick.shoppingHoldUsed"]).toBe("1");
  expect(document.documentElement.dataset.shoppingHold).toBe("1");
  // The row keeps its hint for assistive technology after the tip is gone.
  expect(box("Eggs")).toHaveAttribute("aria-description", shoppingEn.holdTip);
});

it("without storage the document keeps the answer for the session", async () => {
  const user = userEvent.setup();
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new Error("blocked");
  });
  try {
    await open();
    expect(screen.getByText(shoppingEn.holdTip)).toBeInTheDocument();
    await user.click(ring("Milk"));
    expect(screen.queryByText(shoppingEn.holdTip)).not.toBeInTheDocument();
  } finally {
    vi.restoreAllMocks();
  }
});

it("the tip is shown in Swedish with the Swedish labels", async () => {
  await open(shoppingSv);
  expect(
    screen.getByText(
      "Tryck på ringen när du köpt något, eller på varan för att ändra.",
    ),
  ).toBeVisible();
  expect(shoppingSv.holdTip).toBe(
    "Tryck på ringen när du köpt något, eller på varan för att ändra.",
  );
  expect(shoppingEn.holdTip).toBe(
    "Tap the circle when you’ve bought an item, or the item to edit it.",
  );
});

it("a store row ends with a decorative chevron, hidden from assistive tech", async () => {
  await open();
  const row = box("Milk");
  const chevron = row.querySelector(".shopping-chevron");
  expect(chevron).not.toBeNull();
  expect(row.lastElementChild).toBe(chevron);
  expect(chevron?.lastElementChild?.tagName.toLowerCase()).toBe("svg");
  expect(chevron).toHaveAttribute("aria-hidden", "true");
});

// Shift+F10 opens the form with the focus on its first field, so Escape closes it at once and the
// focus goes back to the row; a tap or long press leaves the focus where it was (no keyboard rises on a phone).
it("Shift+F10 puts the focus on the form's first field, and Escape right away closes it onto the row", async () => {
  await open();
  const row = box("Milk");
  row.focus();
  fireEvent.keyDown(row, { key: "F10", shiftKey: true });
  const name = screen.getByLabelText(shoppingEn.name);
  await waitFor(() => expect(name).toHaveFocus());
  fireEvent.keyDown(name, { key: "Escape" });
  expect(editorLegend("Milk")).not.toBeInTheDocument();
  expect(box("Milk")).toHaveFocus();
});

it("a long press opens the form without moving the focus into it", async () => {
  await open();
  fireEvent.contextMenu(screen.getByText("Milk"));
  expect(editorLegend("Milk")).toBeInTheDocument();
  expect(screen.getByLabelText(shoppingEn.name)).not.toHaveFocus();
});

it("with a fine pointer the tip and the row's description name the click and Shift+F10, in both languages", async () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: query === "(pointer: fine)" })),
  );
  try {
    const { unmount } = render(
      <ShoppingView
        transport={adapter()}
        labels={shoppingSv}
        initial={detail}
        fullscreen
      />,
    );
    expect(
      screen.getByText(
        "Klicka på en vara eller tryck Shift+F10 för att ändra.",
      ),
    ).toBeVisible();
    expect(box("Milk")).toHaveAttribute(
      "aria-description",
      shoppingSv.holdKeys,
    );
    unmount();
    await open(shoppingEn);
    expect(
      screen.getByText("Click an item or press Shift+F10 to edit it."),
    ).toBeVisible();
  } finally {
    vi.unstubAllGlobals();
  }
});
