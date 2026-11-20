import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  RECEIPT_MS,
  ReceiptBar,
  useReceipt,
} from "@/features/mcp-apps/ui/receipt";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import {
  rowReceipt,
  useUndoReceipts,
  type UndoReceipt,
} from "@/features/work-app/shared/use-undo-receipts";

/*
 * The bridge between a view's per-row Undo entries and the shared receipt bar: a new entry shows a receipt, a receipt
 * that leaves without Ångra settles its row through onEnd, and an entry that goes first takes its receipt with it.
 * Simulated, in jsdom: this proves the wiring, not a real Claude or Android host.
 */

type Entry = { label: string };
type Entries = Record<string, Entry>;

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

function Harness({
  undos,
  describe,
  onEnd,
}: {
  undos: Entries;
  describe: (key: string, undo: Entry) => UndoReceipt | undefined;
  onEnd: (key: string) => void;
}) {
  const receipt = useReceipt();
  useUndoReceipts({ undos, receipt, describe, onEnd });
  return <ReceiptBar receipt={receipt} />;
}

/** One receipt per entry: "Klar: <label>" and an Ångra that calls `onUndo` with the entry's key. */
function setup(initial: Entries = {}) {
  const onUndo = vi.fn<(key: string) => void>();
  const onEnd = vi.fn<(key: string) => void>();
  const describe = vi.fn((key: string, entry: Entry): UndoReceipt => ({
    message: `Klar: ${entry.label}`,
    undo: { label: "Ångra", onUndo: () => onUndo(key) },
  }));
  const view = render(
    <Harness undos={initial} describe={describe} onEnd={onEnd} />,
  );
  const show = (
    undos: Entries,
    words: (key: string, entry: Entry) => UndoReceipt | undefined = describe,
  ): void => {
    view.rerender(<Harness undos={undos} describe={words} onEnd={onEnd} />);
  };
  return { onUndo, onEnd, describe, show, ...view };
}

const bar = () => document.querySelector(".sk-receipt-slot") as HTMLElement;
const tick = (ms: number) =>
  act(() => {
    vi.advanceTimersByTime(ms);
  });

it("rowReceipt names what happened and the row's title", () => {
  expect(rowReceipt("Klar", "Ring Karin")).toBe("Klar: Ring Karin");
  expect(rowReceipt("Klar", "   ")).toBe("Klar");
});

it("shows nothing while there are no entries, and a receipt with its Ångra when an entry is added", () => {
  const { show, onEnd, describe } = setup();
  expect(bar()).toBeEmptyDOMElement();
  expect(describe).not.toHaveBeenCalled();
  const a = { label: "Ring Karin" };
  show({ a });
  expect(bar()).toHaveTextContent("Klar: Ring Karin");
  expect(screen.getByRole("button", { name: "Ångra" })).toBeInTheDocument();
  expect(onEnd).not.toHaveBeenCalled();
  // The same entry again (the view drew once more) is not a new change: no second receipt.
  show({ a });
  expect(describe).toHaveBeenCalledTimes(1);
});

it("shows the receipt of a new entry in a polite status region", () => {
  const { show } = setup();
  show({ a: { label: "Ring Karin" } });
  expect(bar()).toHaveAttribute("role", "status");
  expect(bar()).toHaveAttribute("aria-live", "polite");
  expect(bar()).toHaveTextContent("Klar: Ring Karin");
});

it("calls onEnd with the row's key once, when the time to undo is up, and not before", () => {
  const { show, onEnd } = setup();
  show({ a: { label: "Ring Karin" } });
  tick(UNDO_MS - 1);
  expect(onEnd).not.toHaveBeenCalled();
  expect(bar()).toHaveTextContent("Klar: Ring Karin");
  tick(1);
  expect(onEnd).toHaveBeenCalledTimes(1);
  expect(onEnd).toHaveBeenCalledWith("a");
  expect(bar()).toBeEmptyDOMElement();
  tick(UNDO_MS * 2);
  expect(onEnd).toHaveBeenCalledTimes(1);
});

it("a receipt without Ångra goes after the short time and settles its row as well", () => {
  const { show, onEnd } = setup();
  show(
    { a: { label: "Ring Karin" } },
    vi.fn(() => ({ message: "Klar: Ring Karin" })),
  );
  expect(screen.queryByRole("button")).not.toBeInTheDocument();
  tick(RECEIPT_MS);
  expect(onEnd).toHaveBeenCalledWith("a");
  expect(bar()).toBeEmptyDOMElement();
});

it("an entry for another key replaces the receipt and settles the row of the old one at once", () => {
  const { show, onEnd } = setup();
  const a = { label: "Ring Karin" };
  show({ a });
  tick(5000);
  show({ a, b: { label: "Betala hyran" } });
  expect(bar()).toHaveTextContent("Klar: Betala hyran");
  expect(bar()).not.toHaveTextContent("Ring Karin");
  expect(onEnd).toHaveBeenCalledTimes(1);
  expect(onEnd).toHaveBeenCalledWith("a");
  // The newer receipt runs its own full time.
  tick(UNDO_MS - 1);
  expect(onEnd).toHaveBeenCalledTimes(1);
  tick(1);
  expect(onEnd).toHaveBeenLastCalledWith("b");
  expect(onEnd).toHaveBeenCalledTimes(2);
});

it("a newer change of the same row replaces its receipt without settling the row", () => {
  const { show, onEnd } = setup();
  show({ a: { label: "Ring Karin" } });
  show({ a: { label: "Ring Karin igen" } });
  expect(bar()).toHaveTextContent("Klar: Ring Karin igen");
  // The row still holds a change: it must not settle under the older receipt.
  expect(onEnd).not.toHaveBeenCalled();
  tick(UNDO_MS);
  expect(onEnd).toHaveBeenCalledTimes(1);
  expect(onEnd).toHaveBeenCalledWith("a");
});

it("several entries added in one render show the last and settle the others at once", () => {
  const { show, onEnd } = setup();
  show({ a: { label: "Ring Karin" }, b: { label: "Betala hyran" } });
  expect(bar()).toHaveTextContent("Klar: Betala hyran");
  expect(onEnd).toHaveBeenCalledTimes(1);
  expect(onEnd).toHaveBeenCalledWith("a");
});

it("when the entry goes first the receipt leaves without calling onEnd", () => {
  const { show, onEnd } = setup();
  show({ a: { label: "Ring Karin" } });
  show({});
  expect(bar()).toBeEmptyDOMElement();
  tick(UNDO_MS * 2);
  expect(onEnd).not.toHaveBeenCalled();
});

it("an entry the view cannot describe ends at once and shows no receipt", () => {
  const { show, onEnd } = setup();
  show(
    { a: { label: "Ring Karin" } },
    vi.fn(() => undefined),
  );
  expect(bar()).toBeEmptyDOMElement();
  expect(onEnd).toHaveBeenCalledTimes(1);
  expect(onEnd).toHaveBeenCalledWith("a");
});

it("Ångra runs the latest describe's undo against the entry the row holds now, and does not call onEnd", async () => {
  const { show, onEnd, onUndo } = setup();
  const a = { label: "Ring Karin" };
  show({ a });
  const latest = vi.fn((key: string, entry: Entry): UndoReceipt => ({
    message: `Klar: ${entry.label}`,
    undo: { label: "Ångra", onUndo: () => onUndo(`${key} (latest)`) },
  }));
  // A new render with the same entry and new words is not a new change.
  show({ a }, latest);
  expect(bar()).toHaveTextContent("Klar: Ring Karin");
  await act(async () => {
    fireEvent.click(screen.getByRole("button", { name: "Ångra" }));
    await Promise.resolve();
  });
  expect(onUndo).toHaveBeenCalledTimes(1);
  expect(onUndo).toHaveBeenCalledWith("a (latest)");
  expect(latest).toHaveBeenLastCalledWith("a", a);
  expect(bar()).toBeEmptyDOMElement();
  tick(UNDO_MS * 2);
  expect(onEnd).not.toHaveBeenCalled();
});

it("Ångra is gone with a row whose entry has already gone", () => {
  const { show, onUndo } = setup();
  show({ a: { label: "Ring Karin" } });
  // The row's own entry goes (a read forgot it) in the same moment as the press: the bar goes with it.
  show({});
  expect(screen.queryByRole("button", { name: "Ångra" })).toBeNull();
  tick(UNDO_MS);
  expect(onUndo).not.toHaveBeenCalled();
});

it("the pointer over the receipt stands the time still, and the row settles when it runs out afterwards", () => {
  const { show, onEnd } = setup();
  show({ a: { label: "Ring Karin" } });
  const receipt = document.querySelector(".sk-receipt") as HTMLElement;
  tick(UNDO_MS - 3000);
  fireEvent.pointerEnter(receipt);
  tick(UNDO_MS * 3);
  expect(onEnd).not.toHaveBeenCalled();
  fireEvent.pointerLeave(receipt);
  tick(2999);
  expect(onEnd).not.toHaveBeenCalled();
  tick(1);
  expect(onEnd).toHaveBeenCalledWith("a");
});

it("never calls onEnd after the view has unmounted", () => {
  const { show, onEnd, unmount } = setup();
  show({ a: { label: "Ring Karin" } });
  unmount();
  tick(UNDO_MS * 2);
  expect(onEnd).not.toHaveBeenCalled();
});
