import { useContext, useEffect, useEffectEvent } from "react";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import type { ShoppingDetail, ShoppingList } from "../transport";

/** The id of the active list changed last, or undefined when there is none: what a wide frame opens first. */
export function latestList(lists: readonly ShoppingList[]): string | undefined {
  let latest: ShoppingList | undefined;
  for (const entry of lists)
    if (!entry.archived && (!latest || entry.updated_at > latest.updated_at))
      latest = entry;
  return latest?.id;
}

/**
 * Fullscreen in a wide frame, where the shell offers its one-row head (≥ 64rem): the head is the shared room head in
 * the shell's row, and the lists stand beside the chosen list (useWideLists).
 */
export function useWideFrame(fullscreen: boolean): boolean {
  const { headSlot } = useContext(RoomSurfaceContext);
  return fullscreen && Boolean(headSlot);
}

/**
 * The lists beside the chosen list (desktop spec 3.4): in a wide frame (useWideFrame) the picker is the list pane and
 * the chosen list the detail.
 *
 * - `split`: the picker and the list stand side by side. It needs something to stand beside (a chosen list, or lists to
 *   choose from); with none the empty picker is the page, as in a narrow frame.
 * - `rail`: what the picker draws as the list pane: the chosen list, and its count from its own read when that read
 *   holds every item (the overview's count may be older than the ticks made since).
 *
 * With no list chosen, the list changed last is opened, so the right side is never empty.
 */
export function useWideLists({
  wide,
  id,
  busy,
  lists,
  detail,
  onChoose,
}: {
  wide: boolean;
  id: string;
  busy: boolean;
  lists: readonly ShoppingList[];
  detail?: ShoppingDetail;
  onChoose: (id: string) => void;
}) {
  const split = wide && (Boolean(id) || lists.length > 0);
  const latest = wide && !id && !busy ? latestList(lists) : undefined;
  const choose = useEffectEvent((next: string) => onChoose(next));
  useEffect(() => {
    if (latest) choose(latest);
  }, [latest]);
  const rail = split
    ? {
        chosen: id,
        openCount:
          detail && detail.next_offset === null
            ? detail.items.filter((item) => !item.purchased).length
            : undefined,
      }
    : undefined;
  return { split, rail };
}
