import { useEffect, useRef, useState } from "react";
import type { PendingKey } from "../../../mcp-apps/idempotency";
import { useRowQueue } from "../../../mcp-apps/ui/row-queue";
import {
  failureNotice,
  type BoardAction,
  type BoardNotice,
} from "../../board/board";
import { appendAgendaPage } from "../../shared/work-items";
import type { WorkAgendaFrame, WorkTransport } from "../../transport/transport";
import type { RowState } from "./use-row-state";

/** True while the view is mounted: a write that outlives it must not set state. */
export function useMounted() {
  const mounted = useRef(true);
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  return mounted;
}

/**
 * The reads and the guarded actions of the agenda: the busy state and the last notice, `run` (one read or bulk write at a
 * time), `reread` and `loadMore`, the row queue and the keys and retry the row writes share. A saved Task, the caller's
 * counter and `refreshKey` ask for a read again; the value each had at mount is not a request.
 */
export function useAgendaSession({
  transport,
  frame,
  onChange,
  onRead,
  rows,
  mounted,
  stale,
  refreshTick,
  refreshKey,
}: {
  transport: WorkTransport;
  frame: WorkAgendaFrame;
  onChange: (next: WorkAgendaFrame) => void;
  onRead?: () => void;
  rows: RowState;
  mounted: { readonly current: boolean };
  /** A Task was saved since this agenda was read: it reads again once shown. */
  stale: boolean;
  /** The caller's read-again counter (absent when the agenda keeps its own filter row). */
  refreshTick: number | undefined;
  refreshKey: number | undefined;
}) {
  const [busy, setBusy] = useState<BoardAction | "idle">("idle");
  const [notice, setNotice] = useState<BoardNotice>();
  // Synchronous guard against a second read or bulk write before React re-renders. Row writes do not take it: they
  // queue per row (a performance measure), so a tap during a write waits instead of being dropped.
  const reading = useRef(false);
  const rowQueue = useRowQueue();
  // The row writes still running or waiting; a read waits for them (never the other way round).
  const inflight = useRef(new Set<Promise<void>>());
  // One key per attempt: a retry of the same write reuses it, as the work card does.
  const pending = useRef(new Map<string, PendingKey>());
  // The write that "Try again" repeats after a failed change.
  const retryWrite = useRef<(() => void) | undefined>(undefined);
  // A read asked for while another one runs waits for it (the asker's mark is kept, not dropped).
  const rereadAgain = useRef(false);
  const { page } = frame;

  // The newest reread, for a read that waited for the one before it and for the effects below.
  const rereadNow = useRef(() => undefined as void);

  /** Resolves when no row write is running or waiting (a read or bulk write starts after the rows are quiet). */
  async function rowsQuiet() {
    while (inflight.current.size > 0)
      await Promise.allSettled([...inflight.current]);
  }
  /** Queues a write on its row: it runs after the row's earlier writes, and rows run side by side. */
  function enqueueRow(key: string, task: () => Promise<void>) {
    const done: Promise<void> = rowQueue.enqueue(key, task).finally(() => {
      inflight.current.delete(done);
    });
    inflight.current.add(done);
  }

  function run(action: BoardAction, work: () => Promise<void>) {
    if (reading.current) return;
    reading.current = true;
    setBusy(action);
    setNotice(undefined);
    const started = inflight.current.size > 0 ? rowsQuiet().then(work) : work();
    void started.finally(() => {
      reading.current = false;
      if (mounted.current) setBusy("idle");
      if (rereadAgain.current && mounted.current) {
        rereadAgain.current = false;
        rereadNow.current();
      }
    });
  }
  /** Shows a page just read as the list now is: no triage mark, no folding or left row, and the caller told. */
  function showRead(next: WorkAgendaFrame["page"]) {
    if (!mounted.current) return;
    rows.resetForRead();
    onChange({ ...frame, page: next });
    onRead?.();
  }
  /** Reads the agenda again and shows it as the list now is. */
  function reread() {
    if (reading.current) {
      rereadAgain.current = true;
      return;
    }
    run("reload", async () => {
      try {
        showRead(await transport.getWorkAgenda(frame.filters));
      } catch (error) {
        if (mounted.current) setNotice(failureNotice(error, "reload"));
      }
    });
  }
  function loadMore() {
    const cursor = page.next_cursor;
    if (!cursor) return;
    run("more", async () => {
      try {
        const later = await transport.getWorkAgenda(frame.filters, cursor);
        if (mounted.current)
          onChange({ ...frame, page: appendAgendaPage(page, later) });
      } catch (error) {
        if (mounted.current) setNotice(failureNotice(error, "more"));
      }
    });
  }
  /** Sets the write that "Try again" repeats. */
  function armRetry(again: () => void) {
    retryWrite.current = again;
  }
  function retry(action: BoardAction) {
    if (action === "move") retryWrite.current?.();
    else if (action === "more") loadMore();
    else reread();
  }

  useEffect(() => {
    rereadNow.current = reread;
  });
  // A Task saved under this agenda is shown again with the agenda: the agenda reads again, once (the mark at mount).
  const staleAtMount = useRef(stale);
  useEffect(() => {
    if (staleAtMount.current) rereadNow.current();
  }, []);

  // The caller asks for a read again by raising the counter; the value at mount is not a request.
  const seenTick = useRef(refreshTick ?? 0);
  useEffect(() => {
    if (refreshTick === undefined || refreshTick === seenTick.current) return;
    seenTick.current = refreshTick;
    rereadNow.current();
  }, [refreshTick]);

  // The same request by a plain prop: a changed refreshKey reads again in place (the value at mount is not one).
  const seenRefreshKey = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === seenRefreshKey.current)
      return;
    seenRefreshKey.current = refreshKey;
    rereadNow.current();
  }, [refreshKey]);

  return {
    busy,
    notice,
    setNotice,
    reading,
    pending,
    retryWrite,
    armRetry,
    rowQueue,
    enqueueRow,
    run,
    reread,
    showRead,
    loadMore,
    retry,
  };
}

/** The agenda session: see `useAgendaSession`. */
export type AgendaSession = ReturnType<typeof useAgendaSession>;
