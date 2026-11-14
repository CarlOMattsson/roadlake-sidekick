import { useCallback, useEffect, useRef, useState } from "react";
import { keyFor, type PendingKey } from "../../../mcp-apps/idempotency";
import { isForbidden } from "../../transport/transport";
import {
  failureState,
  readFailurePhase,
  type ListPhase,
  type MorePhase,
  type Phase,
  type WriteState,
} from "./frame-types";
import { useSingleFlight } from "../../shared/use-single-flight";
import { useMounted } from "../../../mcp-apps/ui/use-mounted";

/**
 * The state every detail frame (Task, Contact, Project) shares: the read phase, the editor flag, the last
 * write's outcome, the guards against stale answers and double writes, and the focus rules. The frame adds
 * its record and calls `sendWrite` / `reload` with the transport call and what to do with the answer.
 */
export function useDetailFrame({
  moves,
  startEditing = false,
}: {
  moves: number;
  /** A compact Contact card's "Edit" opens the frame with the existing editor already open. */
  startEditing?: boolean;
}) {
  const [phase, setPhase] = useState<Phase>("loading");
  const [readError, setReadError] = useState<unknown>();
  const [attempt, setAttempt] = useState(0);
  const [editing, setEditing] = useState(startEditing);
  const [write, setWrite] = useState<WriteState>({ kind: "idle" });
  const heading = useRef<HTMLHeadingElement>(null);
  const banner = useRef<HTMLDivElement>(null);
  // Responses from a superseded load or an unmounted frame must not update state.
  const ticket = useRef(0);
  const mounted = useMounted();
  // Synchronous guard against a second write (double click) before React re-renders.
  const flight = useSingleFlight();
  const pendingWrite = useRef<PendingKey | undefined>(undefined);
  useEffect(() => {
    if (moves > 0) heading.current?.focus({ preventScroll: true });
  }, [moves]);
  useEffect(() => {
    if (write.kind === "conflict") banner.current?.focus();
  }, [write.kind]);
  // The read side of the ticket: a read takes a number, and an answer counts only while it is the latest.
  const takeTicket = useCallback(() => ++ticket.current, []);
  const isLatest = useCallback((taken: number) => taken === ticket.current, []);
  const dropReads = useCallback(() => {
    ticket.current++;
  }, []);
  function retry() {
    setPhase("loading");
    setAttempt((n) => n + 1);
  }
  function stopEdit() {
    pendingWrite.current = undefined;
    setEditing(false);
    setWrite({ kind: "idle" });
    heading.current?.focus();
  }
  /**
   * One durable write. The signature names the action and the version it was based on, so a retry of the
   * same action reuses its key and any other action gets a fresh one. `apply` stores the answer. `receipt` says the
   * frame draws its own receipt for this write (a `completed` line with Ångra), so no plain `saved` stands beside it.
   */
  function sendWrite<R>(
    signature: string,
    action: "save" | "write",
    send: (key: string) => Promise<R>,
    apply: (result: R) => void,
    receipt = false,
  ) {
    if (!flight.enter()) return;
    const pendingKey = keyFor(pendingWrite.current, signature);
    pendingWrite.current = pendingKey;
    setWrite({ kind: "busy" });
    send(pendingKey.key)
      .then((result) => {
        if (!mounted.current) return;
        pendingWrite.current = undefined;
        // This answer is newer than any read still on its way: that read is dropped, and the phase is
        // cleared here, since the dropped read may have been the one to clear "loading".
        ticket.current++;
        setPhase("ready");
        apply(result);
        setWrite({ kind: receipt ? "idle" : "saved" });
      })
      .catch((error: unknown) => {
        if (mounted.current) setWrite(failureState(error, action));
      })
      .finally(() => {
        flight.leave();
      });
  }
  /**
   * Fetches the latest record; the open editor keeps the values the user typed. `answered` runs when the
   * answer arrives on a mounted frame; `apply` runs only if no newer read or write owns the record.
   */
  function reload<R>(
    fetch: () => Promise<R>,
    apply: (result: R) => void,
    answered?: () => void,
  ) {
    if (!flight.enter()) return;
    const current = ++ticket.current;
    setWrite({ kind: "busy" });
    fetch()
      .then((result) => {
        if (!mounted.current) return;
        pendingWrite.current = undefined;
        answered?.();
        if (current === ticket.current) {
          apply(result);
          setPhase("ready");
        }
        setWrite({ kind: "idle" });
        heading.current?.focus();
      })
      .catch((error: unknown) => {
        if (mounted.current) setWrite(failureState(error, "reload"));
      })
      .finally(() => {
        flight.leave();
      });
  }
  return {
    phase,
    setPhase,
    readError,
    setReadError,
    attempt,
    editing,
    setEditing,
    write,
    setWrite,
    heading,
    banner,
    ticket,
    takeTicket,
    isLatest,
    dropReads,
    flight,
    retry,
    stopEdit,
    sendWrite,
    reload,
  };
}

export type DetailFrame = ReturnType<typeof useDetailFrame>;

/**
 * Reads the frame's record when it opens and again on a retry or a new `refreshKey`. `load` must be
 * stable (wrap it in useCallback on the transport and id); `apply` may change on every render.
 */
export function useFrameRead<R>(
  frame: DetailFrame,
  load: () => Promise<R>,
  apply: (result: R) => void,
  refreshKey: number,
) {
  const { takeTicket, isLatest, dropReads, attempt, setPhase, setReadError } =
    frame;
  const applyLatest = useRef(apply);
  useEffect(() => {
    applyLatest.current = apply;
  });
  useEffect(() => {
    const current = takeTicket();
    load()
      .then((result) => {
        if (!isLatest(current)) return;
        applyLatest.current(result);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (isLatest(current)) {
          setReadError(error);
          setPhase(readFailurePhase(error));
        }
      });
    return () => {
      dropReads();
    };
  }, [
    load,
    takeTicket,
    isLatest,
    dropReads,
    attempt,
    refreshKey,
    setPhase,
    setReadError,
  ]);
}

/**
 * A list section of a detail frame (the Task's Contacts, the Project's Tasks). It loads and fails on its
 * own, so the record itself stays visible; "Show more" appends the next page.
 */
export function usePagedSection<T>({
  list,
  enabled = true,
  refreshKey,
}: {
  /** One page: the first when called with no cursor. Must be stable (useCallback). */
  list: (...after: [] | [string]) => Promise<{
    items: T[];
    next_cursor: string | null;
    /** The server cut the list and has no cursor for the rest. */
    truncated?: boolean;
  }>;
  /** False while the section is off (its room is disabled): nothing is read. */
  enabled?: boolean;
  refreshKey: number;
}) {
  const [phase, setPhase] = useState<ListPhase>("loading");
  const [items, setItems] = useState<T[]>([]);
  const [nextCursor, setNextCursor] = useState<string | null>(null);
  const [truncated, setTruncated] = useState(false);
  const [more, setMore] = useState<MorePhase>("idle");
  const [attempt, setAttempt] = useState(0);
  const ticket = useRef(0);
  // One "Show more" page per read generation, claimed before React re-renders the button.
  const pages = useSingleFlight();
  function loadMore() {
    const current = ticket.current;
    if (!nextCursor || !pages.enter(current)) return;
    setMore("busy");
    list(nextCursor)
      .then((page) => {
        if (current !== ticket.current) return;
        setItems((known) => [...known, ...page.items]);
        setNextCursor(page.next_cursor);
        setTruncated(page.truncated === true);
        setMore("idle");
      })
      .catch(() => {
        if (current === ticket.current) setMore("failed");
      })
      .finally(() => pages.leave(current));
  }
  useEffect(() => {
    if (!enabled) return undefined;
    const marker = ticket;
    const current = ++marker.current;
    list()
      .then((page) => {
        if (current !== marker.current) return;
        setItems(page.items);
        setNextCursor(page.next_cursor);
        setTruncated(page.truncated === true);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (current !== marker.current) return;
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
    return () => {
      marker.current++;
    };
  }, [list, enabled, attempt, refreshKey]);
  function retry() {
    setPhase("loading");
    setMore("idle");
    setAttempt((n) => n + 1);
  }
  /** Drops a read or "Show more" page still on its way (its busy state is cleared here). */
  function invalidate() {
    ticket.current++;
    setMore("idle");
  }
  return {
    phase,
    items,
    setItems,
    nextCursor,
    truncated,
    more,
    loadMore,
    retry,
    invalidate,
  };
}

export type PagedSection<T> = ReturnType<typeof usePagedSection<T>>;
