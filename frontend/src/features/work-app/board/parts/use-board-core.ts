import { useEffect, useEffectEvent, useRef, useState } from "react";
import type {
  WorkBoardFrame,
  WorkTask,
  WorkTransport,
} from "../../transport/transport";
import { useRowQueue } from "../../../mcp-apps/ui/row-queue";
import { appendBoardPage } from "../../shared/work-items";
import {
  failureNotice,
  type BoardAction,
  type BoardNotice,
} from "../board-notice";
import type { FocusWanted } from "../board-writes";
import { boardReadFilters, withTaskMoved } from "../board-columns";

export type Busy = "idle" | BoardAction;

type Options = {
  frame: WorkBoardFrame;
  onChange: (next: WorkBoardFrame) => void;
  transport: WorkTransport;
  stale: boolean;
  onRead?: () => void;
  refreshKey?: number;
};

/**
 * The board's reads and the generation every read and write shares: its frame, notice and busy state, the
 * serialized reload, "Visa fler", the per-card write queue and the quiet read that follows the last write.
 */
export function useBoardCore({
  frame,
  onChange,
  transport,
  stale,
  onRead,
  refreshKey,
}: Options) {
  const [busy, setBusy] = useState<Busy>("idle");
  const [notice, setNotice] = useState<BoardNotice>();
  // Synchronous guard: a second click before React re-renders must not start a second read.
  const writing = useRef(false);
  // Card writes queue per card (a tap during a running write waits, it is not dropped); other cards run at once.
  const rowQueue = useRowQueue();
  // Writes running or waiting; the writes that succeeded (the one generation every read and write of the board shares:
  // an answer to a read that started before the latest confirmed write is dropped); and that count when the last quiet
  // read started.
  const inflight = useRef(0);
  const writes = useRef(0);
  const synced = useRef(0);
  const reads = useRef(0);
  const mounted = useRef(true);
  // A read asked for while another one runs waits for it.
  const reloadAgain = useRef(false);
  // The frame of the latest render, so a read that finishes later keeps what was shown meanwhile.
  const latest = useRef(frame);
  // Where focus goes once the board shows the result of a write.
  const focusWanted = useRef<FocusWanted | undefined>(undefined);
  const reloadNow = useRef(() => undefined as void);
  /**
   * One generation for every read and write of the board: the answer of a read counts only when no write was confirmed
   * and no other read was started since it started (a write's end, and the later read, read again).
   */
  function readToken() {
    const at = [writes.current, ++reads.current];
    return () => writes.current === at[0] && reads.current === at[1];
  }
  function notify(next: BoardNotice | undefined) {
    if (mounted.current) setNotice(next);
  }
  /** Replaces the board frame in the navigation stack. */
  function commit(next: WorkBoardFrame) {
    if (!mounted.current) return;
    latest.current = next;
    onChange(next);
  }
  /** Replaces the board frame; the notice a successful read leaves. */
  function show(next: WorkBoardFrame, done?: BoardNotice) {
    commit(next);
    setNotice(done);
  }
  function run(action: BoardAction, work: () => Promise<void>) {
    if (writing.current) return;
    writing.current = true;
    setBusy(action);
    setNotice(undefined);
    void work().finally(() => {
      writing.current = false;
      if (mounted.current) setBusy("idle");
      if (reloadAgain.current && mounted.current) {
        reloadAgain.current = false;
        reloadNow.current();
      }
    });
  }
  /** Reads the board again with the same filters; `done` is the notice a successful read leaves. */
  async function reread(done?: BoardNotice) {
    const fresh = readToken();
    try {
      const next = await transport.getWorkBoard(
        boardReadFilters(latest.current),
      );
      if (!fresh()) return;
      show({ ...latest.current, page: next }, done);
      onRead?.();
    } catch (error) {
      focusWanted.current = undefined;
      notify(failureNotice(error, "reload"));
    }
  }
  function reload() {
    if (writing.current) {
      reloadAgain.current = true;
      return;
    }
    run("reload", () => reread());
  }
  function loadMore() {
    const cursor = frame.page.next_cursor;
    if (!cursor) return;
    run("more", async () => {
      const fresh = readToken();
      try {
        const later = await transport.getWorkBoard(
          boardReadFilters(latest.current),
          cursor,
        );
        if (!fresh()) return;
        show({
          ...latest.current,
          page: appendBoardPage(latest.current.page, later),
        });
      } catch (error) {
        notify(failureNotice(error, "more"));
      }
    });
  }
  /**
   * Runs a card write behind the earlier writes of the same queue `key` (a card, or a column order): a tap that
   * comes while a write runs waits, it is not dropped. When the last write has ended, the board is read once.
   */
  function queueWrite(key: string, work: () => Promise<void>) {
    inflight.current += 1;
    notify(undefined);
    void rowQueue.enqueue(key, work).finally(() => {
      inflight.current -= 1;
      void quietReread();
    });
  }
  /**
   * Once the queues are empty and a write has succeeded since the last read started, reads the board in the
   * background (no lock, no notice). An answer from before a later write is dropped: that write's end reads again.
   */
  async function quietReread() {
    if (inflight.current > 0 || writes.current === synced.current) return;
    synced.current = writes.current;
    const fresh = readToken();
    try {
      const next = await transport.getWorkBoard(
        boardReadFilters(latest.current),
      );
      if (!fresh()) return;
      commit({ ...latest.current, page: next });
      onRead?.();
    } catch (error) {
      notify(failureNotice(error, "reload"));
    }
  }
  /** A write succeeded: its Task is shown at once in its new column, with the version the answer gave. */
  function wrote(task: WorkTask) {
    writes.current += 1;
    const next = withTaskMoved(latest.current.page, task);
    if (next) commit({ ...latest.current, page: next });
  }

  useEffect(() => {
    latest.current = frame;
    reloadNow.current = reload;
  });
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);
  // A Task saved under this board is shown again with the board: the board reads again, once.
  const reloadIfStale = useEffectEvent(() => {
    if (stale) reload();
  });
  useEffect(() => {
    reloadIfStale();
  }, []);
  // A changed refreshKey reads the board again in place; the value at mount is not a request.
  const seenRefreshKey = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === seenRefreshKey.current)
      return;
    seenRefreshKey.current = refreshKey;
    reloadNow.current();
  }, [refreshKey]);

  return {
    transport,
    busy,
    notice,
    rowQueue,
    writes,
    focusWanted,
    latest,
    notify,
    commit,
    reread,
    reload,
    loadMore,
    queueWrite,
    wrote,
  };
}

export type BoardCore = ReturnType<typeof useBoardCore>;
