import { useCallback, useEffect, useRef, useState } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import type { WorkTransport } from "../transport/transport";
import { useMounted } from "../../mcp-apps/ui/use-mounted";
import {
  UNSORTED_COUNT_LIMIT,
  type UnsortedCount,
} from "../fullscreen/parts/tab-data";

type Options = {
  transport: WorkTransport;
  active: boolean;
  refreshKey: number | undefined;
  /** Given by a host that routes: To sort is then a step on its stack, not a cover over the shell. */
  onRoute: ((target: RoomTarget) => void) | undefined;
};

/**
 * The To sort view (Att sortera), which opens from the quiet row after the agenda and not from a tab. While it is open the
 * shell stays mounted and hidden, so the agenda keeps its state, and Back puts the agenda's scroll back. Also the count
 * the row shows.
 */
export function useUnsorted({
  transport,
  active,
  refreshKey,
  onRoute,
}: Options) {
  const aliveRef = useMounted();
  const [sorting, setSorting] = useState(false);
  // The unsorted Task count for the row; undefined until the first read answers.
  const [unsorted, setUnsorted] = useState<UnsortedCount>();
  // The agenda's page scroll when To sort opened; Back puts it back once the agenda shows again.
  const agendaScroll = useRef<number | undefined>(undefined);

  // Counts the reads: only the newest one answers, so a slow older read cannot bring an older count back.
  const ticket = useRef(0);
  /** Reads how many Tasks are unsorted; a failed read leaves the row hidden. */
  const readUnsorted = useCallback(() => {
    const mine = ++ticket.current;
    void (async () => {
      try {
        const page = await transport.listUnsortedTasks(
          null,
          UNSORTED_COUNT_LIMIT,
        );
        if (aliveRef.current && mine === ticket.current)
          setUnsorted({
            count: page.items.length,
            more: page.next_cursor !== null,
          });
      } catch {
        if (aliveRef.current && mine === ticket.current)
          setUnsorted({ count: 0, more: false });
      }
    })();
  }, [transport, aliveRef]);
  // The count is read when the room is shown, and again for each new refreshKey (a write elsewhere, or a minute
  // hidden): one read when both happen together, none while the room is hidden behind a Task or Project.
  const unsortedFor = useRef<number | undefined>(undefined);
  useEffect(() => {
    if (!active || unsortedFor.current === (refreshKey ?? 0)) return;
    unsortedFor.current = refreshKey ?? 0;
    readUnsorted();
  }, [active, refreshKey, readUnsorted]);

  // The view starts at its top; the agenda's scroll is kept for Back.
  function openSorting() {
    if (onRoute) {
      onRoute({ room: "work", view: "unsorted" });
      return;
    }
    agendaScroll.current = window.scrollY;
    window.scrollTo(0, 0);
    setSorting(true);
  }
  // Back shows the agenda again and reads the count, since the view may have sorted Tasks.
  function closeSorting() {
    setSorting(false);
    readUnsorted();
  }
  // Runs after each render: once the agenda shows again after Back, its scroll is put back.
  useEffect(() => {
    if (sorting) return;
    const y = agendaScroll.current;
    if (y === undefined) return;
    agendaScroll.current = undefined;
    window.scrollTo(0, y);
  });

  return { sorting, unsorted, readUnsorted, openSorting, closeSorting };
}
