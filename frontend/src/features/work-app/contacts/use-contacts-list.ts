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

/** What one list read asks for: the trimmed search, the archive switch and the tag filter (only when chosen). */
type ListQuery = { q: string; includeArchived: boolean; tags?: string[] };

function queryOf(frame: WorkContactsFrame): ListQuery {
  const tags = frame.tags ?? [];
  return {
    q: frame.q.trim(),
    includeArchived: frame.includeArchived,
    ...(tags.length > 0 ? { tags } : {}),
  };
}

function matches(frame: WorkContactsFrame, query: ListQuery): boolean {
  return pageMatches(frame.page, query.q, query.includeArchived, query.tags);
}

/**
 * The reading of the Contact list: a debounced search (an answer to an older search is ignored), the archive
 * switch, the tag filter, Show more, and a read again when `refreshKey` changes. The search and the page live in the frame, so
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
  function fetchFirst(query: ListQuery, current: number) {
    transport
      .listContacts(query)
      .then((result) => {
        if (current !== ticket.current) return;
        emit({
          page: {
            items: result.items,
            next_cursor: result.next_cursor,
            ...query,
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
  /** Reads the list as the frame now asks for it; Retry and a refresh call it. */
  function read(query: ListQuery = queryOf(latest.current)) {
    dispatch({ type: "reset" });
    fetchFirst(query, ++ticket.current);
  }

  // A frame without a page, or whose search was interrupted before it was read, reads on mount.
  const readIfMissing = useEffectEvent(() => {
    const start = queryOf(latest.current);
    if (!matches(latest.current, start)) fetchFirst(start, ++ticket.current);
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
  const readAgain = useEffectEvent(() => read(queryOf(frame)));
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
    if (matches(latest.current, queryOf(latest.current))) return;
    timer.current = setTimeout(() => read(), SEARCH_DEBOUNCE_MS);
  }
  /** The archive switch or the tag filter: read at once, unless the shown page already answers it. */
  function changeNow(
    patch: Pick<Partial<WorkContactsFrame>, "includeArchived" | "tags">,
  ) {
    emit(patch);
    clearTimeout(timer.current);
    ticket.current++;
    dispatch({ type: "reset" });
    const query = queryOf(latest.current);
    if (matches(latest.current, query)) return;
    read(query);
  }
  function loadMore() {
    const shown = latest.current.page;
    if (!shown?.next_cursor || more === "busy") return;
    const current = ticket.current;
    dispatch({ type: "moreStarted" });
    transport
      .listContacts(
        {
          q: shown.q,
          includeArchived: shown.includeArchived,
          ...(shown.tags ? { tags: shown.tags } : {}),
        },
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
    changeArchived: (includeArchived: boolean) =>
      changeNow({ includeArchived }),
    changeTags: (tags: string[]) => changeNow({ tags }),
    loadMore,
    forgetPage,
  };
}
