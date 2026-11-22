import { useLayoutEffect, useRef, useState } from "react";

import type { NavState } from "@/features/mcp-apps/nav-state";
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
  /**
   * The ids of the layers of the active room that are shown: the one on top, and in a split pane the list beside it
   * (nav-state splitOf). Joined with spaces, so a new array of the same layers is the same value.
   */
  shownIds: string;
  /** True while a layer holds edits not yet saved: in a split pane it is not read again under them. */
  holdsEdits: (layerId: string) => boolean;
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
  shownIds,
  holdsEdits,
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
  // The layers of the active room as they were last shown; one that stops being shown is booked hidden from then.
  const shownLayers = useRef<readonly string[]>([]);
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
    const shown = shownIds.split(" ");
    if (full)
      for (const room of nav.visited)
        for (const layer of layersOf(nav, room)) {
          present.add(layer.id);
          if (!layerBooks.current.has(layer.id))
            layerBooks.current.set(layer.id, {
              seen: { ...versions.current },
              hiddenAt:
                room === nav.active && shown.includes(layer.id)
                  ? null
                  : clockNow(),
            });
        }
    for (const id of [...layerBooks.current.keys()])
      if (!present.has(id)) layerBooks.current.delete(id);
  }, [nav, full, shownIds]);

  // A layer of the active room is read again when it is shown, if a write in another layer may have changed its domain
  // since it was read, or if it was hidden for more than a minute. Every layer is checked this way, so the one under
  // the top (Back) and other rooms are as fresh as the top. In a split pane both the list and the record beside it are
  // shown: a write in one reads the other again in place (a Task marked done in the detail, its row in the list). A
  // layer that holds edits not yet saved is left alone until they are saved or dropped.
  useLayoutEffect(() => {
    const shown = shownIds === "" ? [] : shownIds.split(" ");
    if (!full || shown.length === 0) {
      shownLayers.current = [];
      return;
    }
    for (const id of shownLayers.current)
      if (!shown.includes(id)) {
        const left = layerBooks.current.get(id);
        if (left) left.hiddenAt = clockNow();
      }
    shownLayers.current = shown;
    // The host was away: every layer counts as hidden for longer than STALE_AFTER_MS, so the check below reads the shown one.
    if (staleSeen.current !== staleTick) {
      staleSeen.current = staleTick;
      for (const kept of layerBooks.current.values()) kept.hiddenAt = 0;
    }
    const layers = layersOf(nav, nav.active);
    const read: string[] = [];
    for (const id of shown) {
      const book = layerBooks.current.get(id);
      const layer = layers.find((candidate) => candidate.id === id);
      // Beside another shown layer, whose writes would otherwise read it again under the user's hands.
      if (!book || !layer || (shown.length > 1 && holdsEdits(id))) continue;
      const written = new Set<RoomId>([nav.active, layer.entry.room]);
      const changed = [...written].some(
        (domain) => versions.current[domain] > book.seen[domain],
      );
      const stale =
        book.hiddenAt !== null && clockNow() - book.hiddenAt > STALE_AFTER_MS;
      book.hiddenAt = null;
      if (!changed && !stale) continue;
      book.seen = { ...versions.current };
      read.push(id);
    }
    if (read.length === 0) return;
    // eslint-disable-next-line react-hooks/set-state-in-effect -- a shown layer reads again once a write in another landed, by design.
    setLayerKeys((keys) => {
      const next = { ...keys };
      for (const id of read) next[id] = (next[id] ?? 0) + 1;
      return next;
    });
  }, [full, nav, shownIds, writes, staleTick, holdsEdits]);

  return { layerKeys, markDirty };
}
