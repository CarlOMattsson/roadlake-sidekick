import { useCallback, useEffect, useRef, useState } from "react";
import { isConflict, queuedPurchase, writeKey } from "../transport";
import type { ShoppingItem, ShoppingTransport } from "../transport";
import { useRowQueue } from "../../mcp-apps/ui/row-queue";
import type { ShoppingRead } from "./use-shopping-read";
import type { ShoppingWrites } from "./use-shopping-writes";

type Params = {
  transport: ShoppingTransport;
  read: ShoppingRead;
  writes: ShoppingWrites;
  /** Called when a purchase reply was stored in `written`, also by a view that has since been replaced. */
  onWritten?: () => void;
};

/**
 * Buying and undoing a purchase: one write per row, queued per row, drawn at once (`wanted`) and held in
 * place with its Undo (`held`) until the server's reply replaces the row.
 *
 * Offline (the mobile app): a purchase that got no answer waits in the phone's outbox (`waiting`, item id → the state
 * that will be sent). The row keeps that state and says "Väntar på nät" instead of going back; it takes no new tap until
 * the outbox has sent it. When the outbox has run and the row has left it, the list is read again.
 */
export function usePurchases({ transport, read, writes, onWritten }: Params) {
  const { written, detailNow, setDetail, setError, reload } = read;
  const { setConflict, setFailedWrite } = writes;
  // A purchase is a write of its own row, not of the whole list: a tap while the row's write runs
  // waits behind it (shown as "Väntar…"), other rows are free. `wanted` is the state the user asked for, drawn
  // at once; the server's reply replaces it, a refusal takes it back.
  const rowQueue = useRowQueue();
  const [wanted, setWanted] = useState<Record<string, boolean>>({});
  // Items bought in this view, as each purchase write returned them (with the new version). While Undo holds,
  // the row stays in its place with "Bought · Undo" (designsystem §3 Ångra): each purchase has its own
  // Undo. They hold until a change of list or page; a reload and other writes keep them.
  const [held, setHeld] = useState<Record<string, ShoppingItem>>({});
  const purchaseKeys = useRef(new Map<string, string>());
  const [waiting, setWaiting] = useState<Record<string, boolean>>({});
  // The same, for the handlers: every change of `waiting` is made through it first.
  const waitingNow = useRef(waiting);
  const offline = transport.offline;
  /** The outbox as read; a row that has left it was sent (or refused), so the list is read again. */
  const applyOutbox = useCallback(
    (queued: ReadonlyMap<string, boolean>) => {
      const sent = Object.keys(waitingNow.current).some(
        (id) => !queued.has(id),
      );
      waitingNow.current = Object.fromEntries(queued);
      setWaiting(waitingNow.current);
      if (sent) void reload();
    },
    [reload],
  );
  // Which read of the outbox is the newest: an older answer may predate a run of the outbox that a newer one has seen.
  const outboxRead = useRef(0);
  const supersedeReads = useCallback(() => {
    outboxRead.current++;
  }, []);
  const refreshOutbox = useCallback(async () => {
    if (!offline) return;
    const mine = ++outboxRead.current;
    const queued = await offline.queuedPurchases();
    if (mine === outboxRead.current) applyOutbox(queued);
  }, [offline, applyOutbox]);
  // The outbox is read at mount (it survives a restart of the app) and after every run of it.
  useEffect(() => {
    if (!offline) return;
    void refreshOutbox();
    const stop = offline.onQueueChanged(() => void refreshOutbox());
    return () => {
      supersedeReads();
      stop();
    };
  }, [offline, refreshOutbox, supersedeReads]);
  // A purchase whose delivery is unknown (no answer): the server may have applied it. The next write of the row
  // replays it with its own key first, so the row's state is known before that write is judged.
  const unsure = useRef(
    new Map<
      string,
      { base: ShoppingItem; buying: boolean; key: string; fingerprint: string }
    >(),
  );
  /** Forgets every purchase of the list that was left (held rows, asked states, keys, unsure deliveries). */
  function resetPurchases() {
    setHeld({});
    setWanted({});
    written.clear();
    purchaseKeys.current.clear();
    unsure.current.clear();
  }
  // Buying or undoing a purchase is one write of that row, against the newest version this view knows
  // of the row. The row shows the asked state at once. A tap while the row's write runs waits behind it ("Väntar…");
  // other rows and the rest of the list stay free. The reply replaces the row, with no read of the list. A reply that
  // does not show the asked state is a failure ("Try again"), and a refusal puts the row back as it was.
  function togglePurchase(row: ShoppingItem) {
    const id = row.id;
    // A row waiting in the outbox is sent as it is; a new tap would race it with a version it does not know yet.
    if (id in waitingNow.current) return;
    const buying = !row.purchased;
    // Buying holds the row in place with its Undo; Undo (or the ring of a held row) is the opposite write.
    setWanted((before) => ({ ...before, [id]: buying }));
    if (buying) setHeld((before) => ({ ...before, [id]: row }));
    setConflict(null);
    setError(null);
    const settle = () => {
      if (rowQueue.pending(id) <= 1)
        setWanted((before) => {
          const rest = { ...before };
          delete rest[id];
          return rest;
        });
    };
    const back = () => {
      if (rowQueue.pending(id) <= 1 && buying)
        setHeld((before) => {
          const rest = { ...before };
          delete rest[id];
          return rest;
        });
    };
    // One purchase write with its key. A refusal that is not a conflict leaves delivery unknown: it is kept to replay.
    const send = async (
      row_: ShoppingItem,
      want: boolean,
      key: string,
      fingerprint: string,
    ) => {
      let reply: { item: ShoppingItem };
      try {
        reply = await transport.purchase(row_, key);
      } catch (caught) {
        if (!isConflict(caught))
          unsure.current.set(id, {
            base: row_,
            buying: want,
            key,
            fingerprint,
          });
        throw caught;
      }
      unsure.current.delete(id);
      purchaseKeys.current.delete(fingerprint);
      const result = reply.item;
      if (result.purchased !== want) throw new Error("purchase not applied");
      written.set(id, result);
      onWritten?.();
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
      setHeld((before) => {
        const next = { ...before };
        if (want) next[id] = result;
        else delete next[id];
        return next;
      });
    };
    void rowQueue.enqueue(id, async () => {
      try {
        const replay = unsure.current.get(id);
        if (replay)
          await send(
            replay.base,
            replay.buying,
            replay.key,
            replay.fingerprint,
          );
        const known = detailNow.current?.items.find((entry) => entry.id === id);
        const own = written.get(id);
        const base =
          own && (!known || own.version >= known.version)
            ? own
            : (known ?? row);
        if (base.purchased === buying) {
          settle();
          return;
        }
        const fingerprint = JSON.stringify([
          "purchase",
          id,
          base.version,
          buying,
        ]);
        const key = purchaseKeys.current.get(fingerprint) ?? writeKey();
        purchaseKeys.current.set(fingerprint, key);
        await send(base, buying, key, fingerprint);
        settle();
      } catch (caught) {
        const queued = queuedPurchase(caught);
        if (queued) {
          // No answer, and the outbox now holds the write with its key: the row keeps the state that will be sent.
          unsure.current.delete(id);
          for (const fp of [...purchaseKeys.current.keys()])
            if (fp.includes(`"${id}"`)) purchaseKeys.current.delete(fp);
          waitingNow.current = {
            ...waitingNow.current,
            [id]: queued.purchased,
          };
          setWaiting(waitingNow.current);
          settle();
          // The outbox may have run before this answer came (its change was handled first and did not know the row):
          // read what it holds now, so a row it already sent is not left waiting until the next run.
          await refreshOutbox();
          return;
        }
        settle();
        back();
        if (isConflict(caught)) {
          // The stored version moved on: the old write can never succeed. Read the list again; the next tap is new.
          unsure.current.delete(id);
          for (const fp of [...purchaseKeys.current.keys()])
            if (fp.includes(`"${id}"`)) purchaseKeys.current.delete(fp);
          setFailedWrite(null);
          setConflict({ rowId: id });
          await reload();
          return;
        }
        // "Try again" repeats this tap; the same version and state reuse the key of this attempt.
        setFailedWrite(() => () => togglePurchase(row));
        setError({ rowId: id });
      }
    });
  }
  return {
    rowQueue,
    wanted,
    waiting,
    held,
    setHeld,
    resetPurchases,
    togglePurchase,
  };
}
