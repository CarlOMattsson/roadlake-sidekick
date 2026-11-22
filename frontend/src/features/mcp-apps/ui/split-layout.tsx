import {
  useContext,
  useEffect,
  useLayoutEffect,
  useRef,
  type ReactNode,
  type Ref,
} from "react";
import { createPortal } from "react-dom";

import { BackHeader } from "./back-header";
import { CloseIcon } from "./icons";
import { RoomSurfaceContext } from "./room-context";

import "./split-layout.css";

/**
 * A list and a record beside it, in a wide frame (desktop spec 2.1). The Sidekick shell draws its panes with it
 * (shell-parts/shell-panes.tsx, by the rule `splitOf` in nav-state.ts); a view that splits inside itself (Shopping's
 * lists) may use it too. Every width rule is a container query on `sk-frame` (split-layout.css): the list is
 * --sk-list-w, a 24 + 1 + 32 gap with the hairline holds the detail, whose content is at most --sk-detail-max and left
 * aligned.
 *
 * - `single`: no box of its own (`display: contents`), so a narrow frame draws exactly what it drew before.
 * - `split` and `aside`: the list's column and the detail's (the record, or the aside: SplitAside or DetailHints).
 * - `drawer`: the wide view keeps the whole row and does not move; the record lies over its right side.
 *
 * The children are the panes, each with `data-pane` ("list", "detail", "drawer"; a hidden one has none). The page
 * scrolls the list. The detail stays in view beside it (sticky under the shell's bar) while it fits the window, and
 * scrolls with the page when it is taller. Only where the host fixes the frame's height (`data-host-height="fixed"`,
 * host-style.ts) is the detail held to the window and scrolls by itself: with a height the app's size decides, a bound
 * taken from the window would shrink the frame in a loop with size-changed.
 */
export type SplitKind = "single" | "split" | "aside" | "drawer";

export function SplitLayout({
  split,
  swapped = false,
  shown,
  children,
}: {
  split: SplitKind;
  /** The record beside the list was just swapped for the next one (a step through the list): it does not slide in. */
  swapped?: boolean;
  /** A key of the record the detail shows: a new one is drawn where the list is scrolled to (`--sk-detail-at`). */
  shown?: string;
  children: ReactNode;
}) {
  const box = useRef<HTMLDivElement>(null);
  // Where the record opens: a detail taller than the window is not sticky (`data-fits="no"` below), so it would open at
  // the list's top, out of view when the list is scrolled. Taken once per record, as how far the list's top lies above
  // the sticky line, and only CSS reads it: it does not follow the scroll, and in a frame the host sizes the frame has
  // no scroll of its own, so the offset is 0 there and makes no loop with size-changed.
  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return;
    const pane = element.querySelector<HTMLElement>(
      ":scope > [data-pane='detail'], :scope > [data-pane='drawer']",
    );
    const line = pane ? Number.parseFloat(getComputedStyle(pane).top) || 0 : 0;
    const above = line - element.getBoundingClientRect().top;
    element.style.setProperty(
      "--sk-detail-at",
      `${Math.max(0, Math.round(above))}px`,
    );
  }, [shown]);
  // Whether the detail fits under the sticky bar (`data-fits`): a detail taller than the window scrolls with the page
  // instead of hiding its end behind a sticky top. Sticky moves nothing in the flow, so the answer never changes the
  // frame's size and makes no loop with size-changed. Written on the box itself, not as state: only CSS reads it.
  useLayoutEffect(() => {
    const element = box.current;
    if (!element) return undefined;
    if (split !== "split" && split !== "drawer") {
      element.removeAttribute("data-fits");
      return undefined;
    }
    const measure = () => {
      const pane = element.querySelector<HTMLElement>(
        ":scope > [data-pane='detail'], :scope > [data-pane='drawer']",
      );
      if (!pane) return;
      const top = Number.parseFloat(getComputedStyle(pane).top) || 0;
      element.setAttribute(
        "data-fits",
        pane.offsetHeight + top <= window.innerHeight ? "yes" : "no",
      );
    };
    measure();
    if (typeof ResizeObserver === "undefined") return undefined;
    const sizes = new ResizeObserver(measure);
    sizes.observe(element);
    for (const child of Array.from(element.children)) sizes.observe(child);
    window.addEventListener("resize", measure);
    return () => {
      sizes.disconnect();
      window.removeEventListener("resize", measure);
    };
  });
  return (
    <div
      ref={box}
      className="sk-split"
      data-split={split}
      data-swapped={swapped || undefined}
    >
      {children}
    </div>
  );
}

/** A record a list row opens, as the shell names it: "work:task:<id>". */
export type RecordRef = { room: string; view: string; id: string };

export function recordKey({ room, view, id }: RecordRef): string {
  return `${room}:${view}:${id}`;
}

/**
 * The attributes of a list row that opens `record`: `data-sk-record`, which the shell gives the focus back to when the
 * detail beside the list closes, and `aria-current` while the record is the one open beside it (row.css draws it
 * chosen: --sk-row-selected). Without a record, or outside a split list, the row gets neither aria-current nor a tone.
 */
export function useRecordRow(record: RecordRef | undefined): {
  "data-sk-record"?: string;
  "aria-current"?: "true";
} {
  const { beside } = useContext(RoomSurfaceContext);
  if (!record) return {};
  const key = recordKey(record);
  return {
    "data-sk-record": key,
    "aria-current": beside === key ? "true" : undefined,
  };
}

/** The record open beside this list (recordKey), or undefined: no split, or nothing open. */
export function useBesideRecord(): string | undefined {
  return useContext(RoomSurfaceContext).beside;
}

/** True on a list drawn beside its detail in a wide frame: stepping through it (j/k) opens each record there. */
export function useSplitList(): boolean {
  return useContext(RoomSurfaceContext).pane === "list";
}

/**
 * A list says what it is now: a column a record opens beside (`list`), or a wide view (`wide`, Status's columns) a
 * record lies over as a drawer. A list that says nothing is a column, except the board view, which is wide.
 */
export function useListLayout(layout: "list" | "wide") {
  const { setLayout } = useContext(RoomSurfaceContext);
  useEffect(() => {
    setLayout?.(layout);
  }, [setLayout, layout]);
}

/**
 * What a room shows beside its list when no record is open (the Journal's day text), drawn in the shell's aside. Where
 * there is no aside (a narrow frame, a record open) it draws nothing.
 */
export function SplitAside({ children }: { children: ReactNode }) {
  const { asideSlot } = useContext(RoomSurfaceContext);
  return asideSlot
    ? createPortal(<div className="sk-split-aside">{children}</div>, asideSlot)
    : null;
}

/**
 * The head of the detail pane: one 44 row. "‹ {parent}" on the left when the pane holds a stack of its own (a Contact
 * opened from its Task), else the kind of what it shows as a muted kicker; on the right the view's own pen and ⋯ (the
 * view portals them into `slotRef`, as into the shell's Back row: BackHeaderActions) and outermost the ×, which closes
 * the detail.
 */
export function PaneHead({
  kind,
  back,
  close,
  slotRef,
}: {
  /** The kind of what the pane shows ("Uppgift"), when there is no Back. */
  kind: string;
  back?: { label: string; onBack: () => void };
  close: { label: string; onClose: () => void };
  slotRef: Ref<HTMLSpanElement>;
}) {
  return (
    <div className="sk-pane-head">
      <BackHeader
        label={back ? back.label : kind}
        onBack={back?.onBack}
        slotRef={slotRef}
        end={
          <button
            type="button"
            className="sk-iconbtn sk-pane-head__close"
            aria-label={close.label}
            title={`${close.label} (Esc)`}
            aria-keyshortcuts="Escape"
            onClick={close.onClose}
          >
            <CloseIcon />
          </button>
        }
      />
    </div>
  );
}

/**
 * The detail pane with nothing open: one quiet sentence ("Välj en uppgift för att se den här") and the keys that
 * reach a record, in the upper third. The keys only where single keys work and the pointer is fine (CSS hides them
 * for a finger).
 */
export function DetailHints({
  sentence,
  keys,
}: {
  sentence: string;
  /** The keys to list, with their meaning; absent: the sentence alone. */
  keys?: { label: string; entries: readonly { keys: string; label: string }[] };
}) {
  return (
    <div className="sk-detail-hints">
      <p className="sk-detail-hints__sentence">{sentence}</p>
      {keys ? (
        <dl className="sk-detail-hints__keys" aria-label={keys.label}>
          {keys.entries.map((entry) => (
            <div key={entry.keys} className="sk-detail-hints__key">
              <dt>
                <kbd>{entry.keys}</kbd>
              </dt>
              <dd>{entry.label}</dd>
            </div>
          ))}
        </dl>
      ) : null}
    </div>
  );
}
