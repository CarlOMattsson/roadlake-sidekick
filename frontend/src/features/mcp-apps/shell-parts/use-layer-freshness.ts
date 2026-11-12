import { useLayoutEffect, useRef, useState } from "react";

import { topOf, type NavState } from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";
import {
  clockNow,
  layersOf,
  STALE_AFTER_MS,
  zeroes,
  type LayerBook,
} from "./shell-layers";

type Options = {
  nav: NavState;
  full: boolean;
  /** The id of the layer on top of the active room. */
  shownId: string | undefined;
  /** The room the card opened in. A write there makes the inline card stale. */
  startRoom: RoomId;
  onInlineStale: () => void;
  staleTick: number;
};

/**
 * Which layers read their data again as they are shown. Each write counts per domain; each mounted layer
 * remembers what it has read and when it was hidden. `layerKeys` counts, per layer, how often it was asked to
 * read again (a room reloads in place when its count changes).
 */
export function useLayerFreshness({
  nav,
  full,
  shownId,
  startRoom,
  onInlineStale,
  staleTick,
}: Options) {
  // Per layer: how often it was asked to read again. A layer that is not here has never been asked.
  const [layerKeys, setLayerKeys] = useState<Record<string, number>>({});
  // Counts the writes of the full view, so the layer on top is checked again when a write lands late.
  const [writes, setWrites] = useState(0);
  // Dirty bookkeeping. versions[domain] counts writes; each mounted layer remembers what it has read.
  const versions = useRef(zeroes());
  const layerBooks = useRef(new Map<string, LayerBook>());
  // The layer on top of the active room as it was last shown, and when it stopped being shown.
  const shownLayer = useRef<string | undefined>(undefined);
  // The staleTick this shell has answered; the one at mount is not a request.
  const staleSeen = useRef(staleTick);

  /** A write in `layerId`: its domains count one more write, and the writing layer is up to date. */
  function markDirty(layerId: string, domains: readonly RoomId[]) {
    if (full && domains.includes(startRoom)) onInlineStale();
    const book = layerBooks.current.get(layerId);
    for (const domain of domains) {
      versions.current[domain] += 1;
      if (book) book.seen[domain] = versions.current[domain];
    }
    if (full) setWrites((count) => count + 1);
  }

  // Every mounted layer is booked with the writes it was mounted with; a layer that is gone is forgotten.
  // A layer that is not the one shown at its mount has not been seen yet, so it counts as hidden from
  // then: a root under a card's first cross-link is read again when Back reaches it after a minute.
  useLayoutEffect(() => {
    const present = new Set<string>();
    if (full)
      for (const room of nav.visited)
        for (const layer of layersOf(nav, room)) {
          present.add(layer.id);
          if (!layerBooks.current.has(layer.id))
            layerBooks.current.set(layer.id, {
              seen: { ...versions.current },
              hiddenAt: room === nav.active && layer.top ? null : clockNow(),
            });
        }
    for (const id of [...layerBooks.current.keys()])
      if (!present.has(id)) layerBooks.current.delete(id);
  }, [nav, full]);

  // The layer on top of the active room is read again when it is shown, if a write in another layer may
  // have changed its domain since it was read, or if it was hidden for more than a minute. Every layer
  // is checked this way, so the one under the top (Back) and other rooms are as fresh as the top.
  useLayoutEffect(() => {
    if (!full || shownId === undefined) {
      shownLayer.current = undefined;
      return;
    }
    if (shownLayer.current !== shownId) {
      const left = shownLayer.current
        ? layerBooks.current.get(shownLayer.current)
        : undefined;
      if (left) left.hiddenAt = clockNow();
      shownLayer.current = shownId;
    }
    // The host was away: every layer counts as hidden for longer than STALE_AFTER_MS, so the check below reads the shown one.
    if (staleSeen.current !== staleTick) {
      staleSeen.current = staleTick;
      for (const kept of layerBooks.current.values()) kept.hiddenAt = 0;
    }
    const book = layerBooks.current.get(shownId);
    if (!book) return;
    const top = topOf(nav, nav.active);
    const written = new Set<RoomId>([nav.active, top.room]);
    const changed = [...written].some(
      (domain) => versions.current[domain] > book.seen[domain],
    );
    const stale =
      book.hiddenAt !== null && clockNow() - book.hiddenAt > STALE_AFTER_MS;
    book.hiddenAt = null;
    if (!changed && !stale) return;
    book.seen = { ...versions.current };
    // eslint-disable-next-line react-hooks/set-state-in-effect -- the check needs the layout after the commit and the write counts in refs; asking for the read is its result.
    setLayerKeys((keys) => ({ ...keys, [shownId]: (keys[shownId] ?? 0) + 1 }));
  }, [full, nav, shownId, writes, staleTick]);

  return { layerKeys, markDirty };
}
