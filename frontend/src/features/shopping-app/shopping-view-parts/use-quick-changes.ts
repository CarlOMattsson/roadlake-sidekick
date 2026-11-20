import { useCallback, useEffect, useRef, useState } from "react";
import { isConflict, writeKey } from "../transport";
import type { ShoppingItem, ShoppingTransport } from "../transport";
import type { ShoppingLabels } from "../labels";
import type { RowQueue } from "../../mcp-apps/ui/row-queue";
import type { ReceiptState } from "../../mcp-apps/ui/receipt";
import type { ShoppingRead } from "./use-shopping-read";
import type { ShoppingWrites } from "./use-shopping-writes";

/** Taps on an amount step that come closer together than this are one write. */
export const QUANTITY_DELAY_MS = 400;

/** A list an item can be moved to. */
export type MoveTarget = { id: string; name: string };

/** An item that was moved to another list and can still be taken back from its receipt. */
type Moved = {
  /** The item as the move answered (in its new list, at its new version); the row as it was until then. */
  item: ShoppingItem;
  to: MoveTarget;
  /** The list it came from. */
  from: string;
  /** The server has answered, so there is a version to undo from. */
  confirmed: boolean;
  /** The bar's receipt of the move, dismissed when the move is refused. */
  receiptId: number;
};

type Params = {
  transport: ShoppingTransport;
  labels: ShoppingLabels;
  read: ShoppingRead;
  writes: ShoppingWrites;
  rowQueue: RowQueue;
  /** Called when an item's reply was stored in `written`, also by a view that has since been replaced. */
  onWritten?: () => void;
  /** The view's receipt bar: a move is confirmed there, with Ångra. */
  receipt: ReceiptState;
  /** A failed Ångra: the view names it in its message box, since the row is gone from the list. */
  onUndoFailed: (id: string, message: string) => void;
};

/** An amount as the tools take it: a plain decimal without trailing zeros. */
const amountText = (value: number) => String(Number(value.toFixed(3)));

/**
 * The two quick changes of an open row in the store view: the amount up or down by one, and a move to another
 * list. Both save at once and draw at once: the row shows the asked amount (`asked`) or has left the list (and the
 * receipt bar says where, with Ångra) before the server has answered, and a refusal puts it back as it was.
 * Taps on the amount that follow each other close together are one write. Each is one write of that row, queued
 * behind the row's other writes, against the newest version this view knows of it; a stale version is a conflict
 * notice and a new read, like the rest of the view.
 */
export function useQuickChanges({
  transport,
  labels: t,
  read,
  writes,
  rowQueue,
  onWritten,
  receipt,
  onUndoFailed,
}: Params) {
  const { written, detailNow, setDetail, setError, reload } = read;
  const { setConflict, setFailedWrite, write } = writes;
  // The amount asked for, by item id. The ref is the same value for the handlers: every change goes through it first.
  const [asked, setAsked] = useState<Record<string, string>>({});
  const askedNow = useRef(asked);
  const timers = useRef(new Map<string, ReturnType<typeof setTimeout>>());
  // One key per write intent, kept across an uncertain delivery, so a retry cannot apply the change twice.
  const keys = useRef(new Map<string, string>());
  // The moves this view made, by item id: what the bar's Ångra takes back. Nothing is drawn from them.
  const movedNow = useRef<Record<string, Moved>>({});

  const changeAsked = useCallback((id: string, text: string | null) => {
    const next = { ...askedNow.current };
    if (text === null) delete next[id];
    else next[id] = text;
    askedNow.current = next;
    setAsked(next);
  }, []);
  const changeMoved = useCallback((id: string, entry: Moved | null) => {
    const next = { ...movedNow.current };
    if (entry === null) delete next[id];
    else next[id] = entry;
    movedNow.current = next;
  }, []);
  /** The newest version of the item this view knows of: the one it has written itself, or else the one it has read. */
  function newest(id: string, fallback?: ShoppingItem) {
    const own = written.get(id);
    const known =
      detailNow.current?.items.find((entry) => entry.id === id) ?? fallback;
    return own && (!known || own.version >= known.version) ? own : known;
  }
  /** Forgets the keys of the item's writes (a conflict: those writes can never succeed). */
  function forget(id: string) {
    for (const fingerprint of [...keys.current.keys()])
      if (fingerprint.includes(`"${id}"`)) keys.current.delete(fingerprint);
  }
  function stopTimer(id: string) {
    clearTimeout(timers.current.get(id));
    timers.current.delete(id);
  }

  /** One write of an amount against `known`, with the key of that attempt; the reply is kept as the newest version of the row. */
  async function updateQuantity(id: string, known: ShoppingItem, want: string) {
    const fingerprint = JSON.stringify(["quantity", id, known.version, want]);
    const key = keys.current.get(fingerprint) ?? writeKey();
    keys.current.set(fingerprint, key);
    const { item: result } = await transport.update(
      known,
      { name: known.name, quantity: want },
      key,
    );
    keys.current.delete(fingerprint);
    written.set(id, result);
    onWritten?.();
    return result;
  }

  /**
   * Writes the amounts whose taps have not yet settled, for a view that is leaving (another list, or closed): their
   * timers would otherwise be dropped with the change. Same queue, keys and version chain as the timer's write, but
   * nothing is drawn: the rows are out of view, and a refused write leaves the stored amount for the next read.
   */
  function flushQuantities() {
    for (const id of [...timers.current.keys()]) {
      stopTimer(id);
      const want = askedNow.current[id];
      const snapshot = newest(id);
      if (want === undefined || !snapshot) continue;
      void rowQueue.enqueue(id, async () => {
        const known = newest(id, snapshot) ?? snapshot;
        if (Number(known.quantity) === Number(want)) return;
        try {
          await updateQuantity(id, known, want);
        } catch {
          // Out of view: the next read of the list shows what was stored.
        }
      });
    }
  }

  /** Asks for an amount and writes it once the taps have stopped (at once when `settled`). */
  function requestQuantity(id: string, text: string, settled: boolean) {
    setConflict(null);
    setError(null);
    changeAsked(id, text);
    stopTimer(id);
    if (settled) sendQuantity(id);
    else
      timers.current.set(
        id,
        setTimeout(() => sendQuantity(id), QUANTITY_DELAY_MS),
      );
  }

  /** The write of an asked amount: the newest version of the row, the asked amount, one key per attempt. */
  function sendQuantity(id: string) {
    stopTimer(id);
    if (!(id in askedNow.current)) return;
    void rowQueue.enqueue(id, async () => {
      const want = askedNow.current[id];
      if (want === undefined) return;
      const known = newest(id);
      // A row that has left the list (moved, or read away) has no amount to write; a move carries the asked one.
      if (!known) {
        if (!(id in movedNow.current)) changeAsked(id, null);
        return;
      }
      if (Number(known.quantity) === Number(want)) {
        changeAsked(id, null);
        return;
      }
      try {
        const result = await updateQuantity(id, known, want);
        setFailedWrite(null);
        setDetail(
          (before) =>
            before && {
              ...before,
              items: before.items.map((entry) =>
                entry.id === id && result.version >= entry.version
                  ? result
                  : entry,
              ),
            },
        );
        // A tap since this write started is still asked for; its own write follows.
        if (askedNow.current[id] === want) changeAsked(id, null);
      } catch (caught) {
        changeAsked(id, null);
        if (isConflict(caught)) {
          // The stored version moved on: this write can never succeed. Read the list again; the next tap is new.
          forget(id);
          setFailedWrite(null);
          setConflict({ rowId: id });
          await reload();
          return;
        }
        // The row goes back to the amount it had; "Try again" asks for the amount once more with the same key.
        setFailedWrite(() => () => requestQuantity(id, want, true));
        setError({ rowId: id, change: true });
      }
    });
  }

  /** One step of the amount, from the amount the row shows. An open item never goes under 1. */
  function stepQuantity(item: ShoppingItem, delta: 1 | -1) {
    const current = Number(item.quantity);
    if (!Number.isFinite(current)) return;
    const next = delta > 0 ? current + 1 : Math.max(1, current - 1);
    if (next === current) return;
    requestQuantity(item.id, amountText(next), false);
  }

  /** Moves the item to the list: it leaves this one at once and stands as a receipt; a refusal puts it back. */
  function moveItem(row: ShoppingItem, to: MoveTarget) {
    const id = row.id;
    if (row.list_id === to.id || id in movedNow.current) return;
    const snapshot = newest(id, row) ?? row;
    const index =
      detailNow.current?.items.findIndex((entry) => entry.id === id) ?? -1;
    // An amount still waiting for its tap to settle goes with the move: one write, not two.
    stopTimer(id);
    setConflict(null);
    setError(null);
    // The bar says it at once; its Ångra waits behind the move in the row's queue, so it never runs before the move.
    const receiptId = receipt.show({
      message: t.itemMoved(snapshot.name, to.name),
      undo: { label: t.undoMove, onUndo: () => undoQueued(id) },
    });
    changeMoved(id, {
      item: snapshot,
      to,
      from: snapshot.list_id,
      confirmed: false,
      receiptId,
    });
    setDetail(
      (before) =>
        before && {
          ...before,
          items: before.items.filter((entry) => entry.id !== id),
        },
    );
    void rowQueue.enqueue(id, async () => {
      const known = newest(id, snapshot) ?? snapshot;
      const quantity = askedNow.current[id] ?? known.quantity;
      const fingerprint = JSON.stringify(["move", id, known.version, to.id]);
      const key = keys.current.get(fingerprint) ?? writeKey();
      keys.current.set(fingerprint, key);
      try {
        const { item: result } = await transport.update(
          known,
          { name: known.name, quantity, list_id: to.id },
          key,
        );
        keys.current.delete(fingerprint);
        written.delete(id);
        changeAsked(id, null);
        setFailedWrite(null);
        changeMoved(id, {
          item: result,
          to,
          from: snapshot.list_id,
          confirmed: true,
          receiptId,
        });
      } catch (caught) {
        // The row comes back where it stood, with the newest version this view knows of it; the bar no longer says
        // it moved.
        receipt.dismiss(receiptId);
        changeMoved(id, null);
        changeAsked(id, null);
        const back = newest(id, snapshot) ?? snapshot;
        setDetail((before) => {
          if (!before || before.items.some((entry) => entry.id === id))
            return before;
          const items = [...before.items];
          items.splice(index < 0 ? items.length : index, 0, back);
          return { ...before, items };
        });
        if (isConflict(caught)) {
          forget(id);
          setFailedWrite(null);
          setConflict({ rowId: id });
          await reload();
          return;
        }
        setFailedWrite(() => () => moveItem(snapshot, to));
        setError({ rowId: id, change: true });
      }
    });
  }

  /** The item came back: its move is forgotten. */
  const release = useCallback(
    (id: string) => {
      if (id in movedNow.current) changeMoved(id, null);
    },
    [changeMoved],
  );

  /** Takes the item back to its list; the list is then read again and shows it. */
  async function undoMove(entry: Moved) {
    const { item } = entry;
    const ok = await write(
      JSON.stringify(["unmove", item.id, item.version, entry.from]),
      (key) =>
        transport.update(
          item,
          { name: item.name, quantity: item.quantity, list_id: entry.from },
          key,
        ),
      () => release(item.id),
      item.id,
    );
    if (!ok) onUndoFailed(item.id, t.itemMoveUndoFailed(item.name));
  }

  /** The bar's Ångra: behind the move in the row's queue, then from the version the move answered with. */
  function undoQueued(id: string) {
    return rowQueue.enqueue(id, async () => {
      const entry = movedNow.current[id];
      if (entry?.confirmed) await undoMoveNow.current(entry);
    });
  }
  // The bar's Ångra outlives the render that showed it: it always runs the newest `undoMove`.
  const undoMoveNow = useRef(undoMove);
  useEffect(() => {
    undoMoveNow.current = undoMove;
  });

  /** Forgets every asked amount and receipt (another list was chosen). */
  function reset() {
    flushQuantities();
    keys.current.clear();
    askedNow.current = {};
    movedNow.current = {};
    setAsked({});
  }
  // The cleanup runs the flush of the last render, which knows the newest rows and writes.
  const flushNow = useRef(flushQuantities);
  useEffect(() => {
    flushNow.current = flushQuantities;
  });
  useEffect(() => () => flushNow.current(), []);

  return { asked, stepQuantity, moveItem, reset };
}
