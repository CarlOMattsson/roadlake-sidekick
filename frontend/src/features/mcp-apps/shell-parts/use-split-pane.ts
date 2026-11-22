import { useCallback, useEffect, useRef, useState } from "react";

import {
  openBeside,
  splitOf,
  type ListLayout,
  type NavEntry,
  type NavState,
  type Split,
} from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";
import type { ShellNavAction } from "@/features/mcp-apps/shell-nav-reducer";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import { recordKey } from "@/features/mcp-apps/ui/split-layout";
import { layersOf } from "./shell-layers";
import type { ShellSplit } from "./shell-panes";

/** The question a split pane asks before it drops unsaved edits beside its list: open `target` there, or close all. */
export type SplitAsk = {
  kind: "beside" | "close";
  target?: NavEntry;
  list: number;
};

type Options = {
  nav: NavState;
  /** A wide frame where the shell drives the rooms (the same frame whose head is one row). */
  wide: boolean;
  labels: SidekickShellLabels;
  /** Single keys work here (fullscreen, local navigation, the switch on): the hints list them. */
  keys: boolean;
  /** The keys the shell and the rooms on top have bound now ("j", "n"): the hints name only those. */
  bound: ReadonlySet<string>;
  dispatch: (action: ShellNavAction) => void;
  /** True when one of these layers holds unsaved edits (the shell's unsaved registry). */
  isDirty: (layerIds: string[]) => boolean;
  /** Opens the unsaved question on the layer on top, for a step that would drop edits beside the list. */
  askFirst: (question: SplitAsk) => void;
  /** Closes the question, when a step goes ahead. */
  clearAsk: () => void;
  /** Whether the shell moves the focus to the heading of the layer on top after this step. */
  focusAfter: (move: boolean) => void;
  /** The shell's own push, for a layer that is not a split pane's list. */
  push: (target: NavEntry, options?: { replace?: boolean }) => void;
};

/**
 * The shell's split pane (desktop spec 2.1): in a wide frame the list a record was opened from stays beside it
 * (nav-state splitOf), and a record opened from that list takes the place of the one shown (openBeside) instead of
 * building a stack. The page's scroll belongs to the list then, so it stays put when records come and go; the focus
 * stays on the row for a click or j/k and goes to the detail on Enter; and the row takes it back when the detail
 * closes. Edits not yet saved beside the list are asked about first, as a Back asks.
 */
export function useSplitPane({
  nav,
  wide,
  labels,
  keys,
  bound,
  dispatch,
  isDirty,
  askFirst,
  clearAsk,
  focusAfter,
  push,
}: Options) {
  // What each list said it is now (useListLayout: Work's Status tab is a wide view), by layer id.
  const [layouts, setLayouts] = useState<Record<string, ListLayout>>({});
  const setLayout = useCallback((layerId: string, layout: ListLayout) => {
    setLayouts((known) =>
      known[layerId] === layout ? known : { ...known, [layerId]: layout },
    );
  }, []);
  // The detail head's place for the view's pen and ⋯, and the aside's place for a room's SplitAside.
  const [paneSlot, setPaneSlot] = useState<HTMLSpanElement | null>(null);
  const [asideSlot, setAsideSlot] = useState<HTMLElement | null>(null);

  // What the last input was: a record opened beside the list takes the focus to the detail only on Enter or Space.
  const lastKey = useRef<string | undefined>(undefined);
  useEffect(() => {
    const onKey = (event: KeyboardEvent) => {
      lastKey.current = event.key;
    };
    const onPointer = () => {
      lastKey.current = undefined;
    };
    window.addEventListener("keydown", onKey, true);
    window.addEventListener("pointerdown", onPointer, true);
    return () => {
      window.removeEventListener("keydown", onKey, true);
      window.removeEventListener("pointerdown", onPointer, true);
    };
  }, []);
  // The row (its data-sk-record) the focus goes back to when the detail beside its list closes.
  const focusRow = useRef<string | undefined>(undefined);

  /** The row of `layer` to give the focus to after the detail closed, once; undefined when there is none. */
  const takeRow = useCallback(
    (layer: HTMLElement | null | undefined): HTMLElement | undefined => {
      const key = focusRow.current;
      focusRow.current = undefined;
      if (!key) return undefined;
      // A view may keep a hidden tab drawn with the same record (Work's Agenda under its Status): the drawn row wins.
      const rows = Array.from(
        layer?.querySelectorAll<HTMLElement>("[data-sk-record]") ?? [],
      ).filter((element) => element.dataset.skRecord === key);
      const row =
        rows.find((element) => element.getClientRects().length > 0) ?? rows[0];
      // The row itself when it takes the focus (Agenda's), else its open control (data-sk-open), else its first one.
      if (!row || row.hasAttribute("tabindex")) return row;
      return (
        row.querySelector<HTMLElement>("[data-sk-open]") ??
        row.querySelector<HTMLElement>("button, a[href]") ??
        undefined
      );
    },
    [],
  );

  function splitFor(room: RoomId, state: NavState = nav): Split {
    const told: Partial<Record<number, ListLayout>> = {};
    layersOf(nav, room).forEach((layer, index) => {
      const layout = layouts[layer.id];
      if (layout) told[index] = layout;
    });
    return splitOf(state, room, { wide, layouts: told });
  }
  const split = splitFor(nav.active);
  const besideOpen = split.kind === "split" || split.kind === "drawer";
  const layers = layersOf(nav, nav.active);
  const topId = layers.at(-1)?.id;

  /** The layer the page's scroll belongs to: the list of a split pane, the layer on top otherwise. */
  function scrollDepth(room: RoomId): number {
    const roomSplit = room === nav.active ? split : splitFor(room);
    return roomSplit.kind === "single"
      ? nav.stacks[room].length
      : roomSplit.list;
  }

  /** The layers shown in the active room, joined with spaces: the one on top, and the list of a split pane. */
  const shownIds = (
    split.kind === "single"
      ? [topId]
      : split.kind === "aside"
        ? [layers[split.list]?.id]
        : [layers[split.list]?.id, layers[split.detail]?.id]
  )
    .filter((id) => id !== undefined)
    .join(" ");

  function remember(entry: NavEntry | undefined) {
    focusRow.current = entry?.id
      ? recordKey({ room: entry.room, view: entry.view, id: entry.id })
      : undefined;
  }

  function showBeside(target: NavEntry, list: number) {
    clearAsk();
    const key = lastKey.current;
    focusAfter(key === "Enter" || key === " ");
    dispatch({ type: "beside", target, list });
  }

  function closeNow(list: number) {
    remember(layers[list + 1]?.entry);
    focusAfter(true);
    dispatch({ type: "close-beside", list });
  }

  /** A record opened from the split list: beside it, after asking about unsaved edits there. */
  function openFromList(target: NavEntry, list: number) {
    const above = layers.slice(list + 1).map((layer) => layer.id);
    if (isDirty(above)) askFirst({ kind: "beside", target, list });
    else showBeside(target, list);
  }

  /** The × of the detail: closes all that is open beside the list, after asking about unsaved edits there. */
  function requestClose() {
    if (!besideOpen) return;
    const above = layers.slice(split.list + 1).map((layer) => layer.id);
    if (isDirty(above)) askFirst({ kind: "close", list: split.list });
    else closeNow(split.list);
  }

  /** The navigate a layer gets: a split pane's list opens its records beside itself; every other layer pushes. */
  function navigateFrom(layerId: string | undefined) {
    return (target: NavEntry, options?: { replace?: boolean }) => {
      const index = layers.findIndex((layer) => layer.id === layerId);
      if (split.kind !== "single" && index !== -1 && index === split.list)
        openFromList(target, split.list);
      // A wide view with nothing open (the Status board): its record opens as the drawer over it, as from a list.
      else if (
        split.kind === "single" &&
        index !== -1 &&
        index === layers.length - 1 &&
        !options?.replace &&
        splitFor(nav.active, openBeside(nav, index, target)).kind === "drawer"
      )
        openFromList(target, index);
      else push(target, options);
    };
  }

  return {
    split,
    besideOpen,
    shownIds,
    scrollDepth,
    navigateFrom,
    requestClose,
    /** Goes ahead with a split question after the user chose to drop the edits. */
    answer(question: SplitAsk) {
      if (question.kind === "beside" && question.target)
        showBeside(question.target, question.list);
      else closeNow(question.list);
    },
    /**
     * A Back is about to pop the top: its record is remembered, so the row of that record takes the focus in the layer
     * Back returns to (the list, a narrow frame's too) when it has one, else the heading as before (takeRow).
     */
    beforeBack() {
      remember(layers.at(-1)?.entry);
    },
    takeRow,
    /** What ShellPanes draws the split with, besides the Back of the detail's own stack. */
    panes: {
      paneSlot,
      setPaneSlot,
      asideSlot,
      setAsideSlot,
      setLayout,
      hintKeys: keys
        ? {
            label: labels.split.keysLabel,
            entries: [
              ...(bound.has("j")
                ? [{ keys: "j k", label: labels.split.rows }]
                : []),
              { keys: "Enter", label: labels.split.open },
              ...(bound.has("n")
                ? [{ keys: "N", label: labels.split.add }]
                : []),
              { keys: "?", label: labels.split.help },
            ],
          }
        : undefined,
    } satisfies Partial<ShellSplit>,
  };
}
