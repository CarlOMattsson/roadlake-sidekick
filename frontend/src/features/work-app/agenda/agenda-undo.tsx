import { useEffect, useRef } from "react";
import type { WorkLabels } from "../shared/labels";
import { agendaLabelsFor } from "./agenda-labels";

/**
 * Undo in the fullscreen views (designsystem §3): every status change and date move in the
 * agenda, the board and To sort can be undone from its own row for `UNDO_MS` (mcp-apps/ui/undo-hold.ts). Undo writes the previous value with
 * a new key, against the version the change left.
 */

/** The last status change of one record: the status it had, the status it got, and the version it has now. */
export type AgendaUndo = {
  /** `kind:id` of the record, as `cardKey` gives it. */
  key: string;
  taskId: string;
  from: string;
  to: string;
  /** The Task version after the change; the undo write is made against it. */
  version: number;
  /**
   * A due-date move from an overdue row: the due instant it had (null for none), and the label the
   * line shows instead of a status. Undo writes the due instant back; `from` and `to` are then unused.
   */
  due?: { from: string | null; label: string };
  /**
   * A recurring Task marked done keeps its completion on record (`last_completed_at`) when it is reopened. This is the
   * value it had before the change; Undo writes it back together with the due date, so the Task leaves the journal's `done` section.
   */
  lastCompleted?: { from: string | null };
  /**
   * The change marked the Task done (its `completed` state). When the agenda's Undo runs out, only such a row folds away from its
   * group; a due move of a Task that is already done keeps its row.
   */
  completed?: boolean;
  /** The row had left its group (stood in Klar idag) when the change was made; Undo puts it back there. */
  hadLeft?: boolean;
  /** The title of the Task the change was made to (the Task view's step Undo names it). */
  title?: string;
};

/** The longest Task title a step's Undo line shows, in characters; a longer one is cut and ends with "…". */
export const UNDO_TITLE_MAX = 40;

/** A Task title for the Undo line: at most `max` characters, the last one "…" when the title was cut. */
export function shortTitle(title: string, max = UNDO_TITLE_MAX): string {
  const text = title.trim();
  const chars = Array.from(text);
  if (chars.length <= max) return text;
  const head = chars
    .slice(0, max - 1)
    .join("")
    .trimEnd();
  return `${head}…`;
}

/** Replaces each `{name}` in a label template with its value; unknown names stay as they are. */
export function fillLabel(
  template: string,
  values: Record<string, string>,
): string {
  return template.replace(/\{(\w+)\}/g, (whole, name: string) =>
    Object.prototype.hasOwnProperty.call(values, name)
      ? (values[name] ?? whole)
      : whole,
  );
}

/** The nearest box above `node` that can scroll (overflow auto, scroll or hidden), or the document's root. */
export function scrollBoxOf(node: HTMLElement): HTMLElement {
  let box = node;
  while (
    box.parentElement &&
    !/auto|scroll|hidden/.test(getComputedStyle(box).overflowY)
  )
    box = box.parentElement;
  return box;
}

/** The scroll place of the page and of the nearest box that scrolls, as text: a change of it means the user scrolled. */
function scrollPlace(node: HTMLElement): string {
  return `${window.scrollY}:${scrollBoxOf(node).scrollTop}`;
}

/**
 * Scrolls its element into view (`nearest`, both ways) when it mounts and when `key` changes, so what the app shows after
 * an action ends above the host's reply field: its scroll margin is the foot reserve (agenda.css). The row's quick choices
 * and its Ångra share it. A change of `key` comes from a write that may land later, so it scrolls only while
 * the element is still in the document and the user has not scrolled since the last render that had no key.
 */
export function useNearest<T extends HTMLElement>(key?: unknown) {
  const el = useRef<T>(null);
  // The scroll place the last render without a key left; null until there is one.
  const place = useRef<string | null>(null);
  // The two effects run in this order: the scroll is asked first, against the place the render before the change left.
  useEffect(() => {
    const node = el.current;
    if (
      node?.isConnected &&
      (place.current === null || scrollPlace(node) === place.current)
    ) {
      // The nearest box that can scroll (or the document's root) and its place before the scroll.
      const scroller = scrollBoxOf(node);
      const scrollerTop = scroller.scrollTop;
      node.scrollIntoView?.({ block: "nearest", inline: "nearest" });
      // Only a scroll that happened is corrected, in the box that scrolled (no jump when nothing scrolled).
      if (scroller.scrollTop !== scrollerTop) {
        // A group heading the scroll left on its way out under the tab row (pushed above its sticky
        // line) goes under it whole, with the 8 under it that end its section, so no heading and no last row's
        // descender stands cut at the chrome's edge.
        for (const head of document.querySelectorAll(
          ".work-agenda-group-head",
        )) {
          const box = head.getBoundingClientRect();
          const line = parseFloat(getComputedStyle(head).top);
          const cut = box.bottom + 8 - line;
          if (box.top < line - 0.5 && cut > 0) scroller.scrollBy(0, cut);
        }
      }
    }
  }, [key]);
  useEffect(() => {
    if (!key && el.current) place.current = scrollPlace(el.current);
  });
  return el;
}

/**
 * The state line of a row whose change can still be undone (designsystem §0.6): the meta line gives way to `completed`
 * (or `movedTo` with the new date) and the row stays where it was, with its height. While the change is written the
 * line says "Moving…". The Ångra and its time are the view's receipt bar's (`useUndoReceipts`), never the row's. The
 * line is a polite live region (`role="status"`); focus is not moved, and it scrolls itself above the reply field when
 * it shows (`useNearest`). The wrapper (`.work-agenda-undo`) has `display: contents`, so the line is placed by the
 * row's grid.
 */
export function UndoMeta({
  text,
  moving = false,
  labels: t,
}: {
  /** What the change did, in the meta line's words: `completed`, `movedTo`. */
  text: string;
  /** The change is being written: the line says so. */
  moving?: boolean;
  labels: WorkLabels;
}) {
  const done = !moving;
  const nearest = useNearest<HTMLParagraphElement>(done);
  return (
    <div className="work-agenda-undo">
      <p role="status" ref={nearest}>
        {done ? text : agendaLabelsFor(t.dateLocale).moving}
      </p>
    </div>
  );
}
