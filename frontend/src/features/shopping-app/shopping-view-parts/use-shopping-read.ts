import { useCallback, useEffect, useRef, useState } from "react";
import type {
  ShoppingDetail,
  ShoppingItem,
  ShoppingList,
  ShoppingTransport,
} from "../transport";

type Params = {
  transport: ShoppingTransport;
  initial?: ShoppingDetail;
  listId?: string;
  store?: string;
  refreshKey?: number;
  /** The confirmed rows owned by the room; the view keeps its own map when there is none. */
  writtenFrom?: Map<string, ShoppingItem>;
  writtenTick?: number;
};

/**
 * Reading side of the view: the lists page, the chosen list and its rows, the busy flag and the list-level
 * error. `reload` is the one read (lists and list together); a changed transport, list, page or `refreshKey`
 * reads again.
 */
export function useShoppingRead({
  transport,
  initial,
  listId,
  store,
  refreshKey,
  writtenFrom,
  writtenTick,
}: Params) {
  const [lists, setLists] = useState<ShoppingList[]>([]);
  const [listOffset, setListOffset] = useState(0);
  const [nextLists, setNextLists] = useState<number | null>(null);
  const [id, setId] = useState(listId ?? initial?.shopping_list.id ?? "");
  const [offset, setOffset] = useState(0);
  const [detail, setDetail] = useState<ShoppingDetail | undefined>(initial);
  const [busy, setBusy] = useState(false);
  // The failure notice ("Try again", "Refresh"). A row's own failed write is shown in that row; null is
  // the list-level notice at the top (a failed read, a create, an add or an Undo).
  const [error, setError] = useState<{ rowId: string | null } | null>(null);
  // When the last read got no answer and was answered from the phone's offline copy: when that copy was read (epoch
  // millis). Null for a read the server answered. Only the mobile app has a copy (`transport.offline`).
  const [copiedAt, setCopiedAt] = useState<number | null>(null);
  const generation = useRef(0);
  // The items as each purchase write returned them. A read that started before the write and answers after it
  // never takes a row back to an older version.
  const [ownWritten] = useState(() => new Map<string, ShoppingItem>());
  const written = writtenFrom ?? ownWritten;
  const detailNow = useRef<ShoppingDetail | undefined>(initial);
  // eslint-disable-next-line react-hooks/refs -- the ref holds the latest detail for the read callbacks, which run after the render.
  detailNow.current = detail;
  // The snapshot the opening result carried: the first read of that list is not repeated.
  const seeded = useRef<ShoppingDetail | undefined>(initial);
  // The first read of the lists in this mount: a single list with nothing chosen opens at once, only then.
  const firstRead = useRef(true);
  // The lists page last read, with the transport and offset it was read for. Choosing a list reads that list
  // only: the lists are read again on an explicit reload (a write, Refresh, a changed refreshKey), on a new
  // page or with a new transport. So a first visit reads the lists once, also when one list opens at once.
  const listsRead = useRef<{
    transport: ShoppingTransport;
    offset: number;
  } | null>(null);
  /** The rows of a read with the newer versions of the rows this view has written itself. */
  const fresher = useCallback(
    (data: ShoppingDetail): ShoppingDetail => ({
      ...data,
      items: data.items.map((item) => {
        const own = written.get(item.id);
        return own && own.version > item.version ? own : item;
      }),
    }),
    [written],
  );
  useEffect(() => {
    if (writtenTick === undefined) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a write of the list is folded into the detail the view shows once it is reported.
    setDetail((before) => {
      if (!before) return before;
      const next = fresher(before);
      return next.items.some((item, i) => item !== before.items[i])
        ? next
        : before;
    });
  }, [writtenTick, fresher]);
  const reload = useCallback(
    async (force = true) => {
      const ticket = ++generation.current;
      // The opening snapshot is the first read of that list; the register is still read.
      const seed = seeded.current;
      seeded.current = undefined;
      const seededNow =
        !force &&
        seed?.shopping_list.id === id &&
        offset === 0 &&
        (seed.store ?? null) === (store ?? null);
      const known = listsRead.current;
      const readLists =
        force ||
        known === null ||
        known.transport !== transport ||
        known.offset !== listOffset;
      setBusy(true);
      setError(null);
      try {
        const [page, data] = await Promise.all([
          readLists ? transport.lists(listOffset) : Promise.resolve(undefined),
          id && !seededNow
            ? transport.get(id, offset, store)
            : Promise.resolve(undefined),
        ]);
        if (ticket !== generation.current) return;
        if (page) {
          listsRead.current = { transport, offset: listOffset };
          setLists(page.lists);
          setNextLists(page.next_offset);
        }
        if (page || data) {
          const at = [data, page]
            .map((answer) => answer && transport.offline?.readAt(answer))
            .find((value) => value !== undefined);
          setCopiedAt(at ?? null);
        }
        if (data) setDetail(fresher(data));
        else if (!id) setDetail(undefined);
        if (firstRead.current && page) {
          firstRead.current = false;
          // Exactly one list and nothing chosen: open it at once. Later "All lists" shows the rows again.
          const [only] = page.lists;
          if (
            !id &&
            only &&
            page.lists.length === 1 &&
            page.next_offset === null &&
            listOffset === 0
          )
            setId(only.id);
        }
      } catch {
        if (ticket === generation.current) setError({ rowId: null });
      } finally {
        if (ticket === generation.current) setBusy(false);
      }
    },
    [transport, id, offset, listOffset, store, fresher],
  );
  useEffect(() => {
    const marker = generation;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the list reads when it opens, which sets its loading state first, by design.
    void reload(false);
    return () => {
      marker.current++;
    };
  }, [reload]);
  // A changed refreshKey reads the list again on the spot: no remount, and only the data is replaced.
  const refreshSeen = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === refreshSeen.current) return;
    refreshSeen.current = refreshKey;
    void reload();
  }, [refreshKey, reload]);
  return {
    lists,
    listOffset,
    setListOffset,
    nextLists,
    id,
    setId,
    offset,
    setOffset,
    detail,
    setDetail,
    busy,
    setBusy,
    error,
    setError,
    copiedAt,
    written,
    detailNow,
    reload,
  };
}

export type ShoppingRead = ReturnType<typeof useShoppingRead>;
