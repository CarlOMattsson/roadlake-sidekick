import { useEffect, useEffectEvent, useReducer, useRef } from "react";
import {
  isForbidden,
  type WorkContactsFrame,
  type WorkTransport,
} from "../transport/transport";
import {
  contactsListReducer,
  initialContactsListState,
  pageMatches,
} from "./contacts-list-state";

const SEARCH_DEBOUNCE_MS = 300;

/**
 * The reading of the Contact list: a debounced search (an answer to an older search is ignored), the archive
 * switch, Show more, and a read again when `refreshKey` changes. The search and the page live in the frame, so
 * coming back from a Contact shows the same list; every change goes out through `onChange`.
 */
export function useContactsList({
  frame,
  onChange,
  transport,
  refreshKey,
}: {
  frame: WorkContactsFrame;
  onChange: (before: WorkContactsFrame, next: WorkContactsFrame) => void;
  transport: WorkTransport;
  /** Reads the list again in place when it changes; the value at mount is not a request. */
  refreshKey?: number;
}) {
  const [state, dispatch] = useReducer(
    contactsListReducer,
    initialContactsListState,
  );
  const { more } = state;
  const timer = useRef<ReturnType<typeof setTimeout>>(undefined);
  // Bumped by every change of the search and every read; only the newest answer is applied.
  const ticket = useRef(0);
  // The newest frame this view has emitted, so two changes in one event do not use a stale base.
  const latest = useRef(frame);

  function emit(patch: Partial<WorkContactsFrame>) {
    const next = { ...latest.current, ...patch };
    onChange(latest.current, next);
    latest.current = next;
  }
  /** Reads the first page; the answer replaces the page unless a newer search has started. */
  function fetchFirst(q: string, includeArchived: boolean, current: number) {
    transport
      .listContacts({ q, includeArchived })
      .then((result) => {
        if (current !== ticket.current) return;
        emit({
          page: {
            items: result.items,
            next_cursor: result.next_cursor,
            q,
            includeArchived,
          },
        });
      })
      .catch((failure: unknown) => {
        if (current !== ticket.current) return;
        dispatch({
          type: "failed",
          cause: failure,
          forbidden: isForbidden(failure),
        });
      });
  }
  function read(q: string, includeArchived: boolean) {
    dispatch({ type: "reset" });
    fetchFirst(q, includeArchived, ++ticket.current);
  }

  // A frame without a page, or whose search was interrupted before it was read, reads on mount.
  const readIfMissing = useEffectEvent(() => {
    const start = latest.current;
    if (!pageMatches(start.page, start.q.trim(), start.includeArchived))
      fetchFirst(start.q.trim(), start.includeArchived, ++ticket.current);
  });
  useEffect(() => {
    const marker = ticket;
    const pendingSearch = timer;
    readIfMissing();
    return () => {
      clearTimeout(pendingSearch.current);
      marker.current++;
    };
  }, [transport]);
  // A changed refreshKey reads the list again with the same search and archive switch, in place.
  const seenRefreshKey = useRef(refreshKey);
  const readAgain = useEffectEvent(() =>
    read(frame.q.trim(), frame.includeArchived),
  );
  useEffect(() => {
    if (refreshKey === undefined || refreshKey === seenRefreshKey.current)
      return;
    seenRefreshKey.current = refreshKey;
    readAgain();
  }, [refreshKey]);

  function changeQuery(value: string) {
    emit({ q: value });
    // An answer to the previous search, or a Show more of it, is now old.
    ticket.current++;
    clearTimeout(timer.current);
    dispatch({ type: "reset" });
    const q = value.trim();
    if (pageMatches(latest.current.page, q, latest.current.includeArchived))
      return;
    timer.current = setTimeout(
      () => read(q, latest.current.includeArchived),
      SEARCH_DEBOUNCE_MS,
    );
  }
  function changeArchived(includeArchived: boolean) {
    emit({ includeArchived });
    clearTimeout(timer.current);
    ticket.current++;
    dispatch({ type: "reset" });
    const q = latest.current.q.trim();
    if (pageMatches(latest.current.page, q, includeArchived)) return;
    read(q, includeArchived);
  }
  function loadMore() {
    const shown = latest.current.page;
    if (!shown?.next_cursor || more === "busy") return;
    const current = ticket.current;
    dispatch({ type: "moreStarted" });
    transport
      .listContacts(
        { q: shown.q, includeArchived: shown.includeArchived },
        shown.next_cursor,
      )
      .then((result) => {
        const base = latest.current.page;
        if (current !== ticket.current || !base) return;
        const seen = new Set(base.items.map((contact) => contact.id));
        emit({
          page: {
            ...base,
            items: [
              ...base.items,
              ...result.items.filter((contact) => !seen.has(contact.id)),
            ],
            next_cursor: result.next_cursor,
          },
        });
        dispatch({ type: "moreDone" });
      })
      .catch(() => {
        if (current === ticket.current) dispatch({ type: "moreFailed" });
      });
  }
  /** The list read before does not have a new Contact: it is read again when it is shown next. */
  function forgetPage() {
    emit({ page: undefined });
  }

  return {
    error: state.error,
    cause: state.cause,
    more,
    read,
    changeQuery,
    changeArchived,
    loadMore,
    forgetPage,
  };
}
