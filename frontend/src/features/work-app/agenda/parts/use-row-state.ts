import { useEffect, useRef, useState, type RefObject } from "react";
import type { AgendaUndo } from "../agenda-undo";
import { cardKey } from "../../shared/work-items";
import type { WorkItemRecord, WorkTask } from "../../transport/transport";
import {
  LEAVE_MS,
  afterWrite,
  currentWith,
  type Override,
} from "./agenda-helpers";

/** What the agenda holds per row on top of the page it read: the optimistic state of its writes. */
export type RowState = ReturnType<typeof useRowState>;

/**
 * The optimistic state of the agenda's rows, by row key: the status and due date each row last wrote (`overrides`),
 * the Undo each change still offers, the rows a triage move muted, and the rows of Klar idag that fold away
 * (`leaving`) and have left their group (`left`). The refs hold the latest value at once, so a queued write reads what
 * the one before it left.
 */
export function useRowState({
  items,
  root,
  mounted,
}: {
  /** The records of the page, to find the row an expired Undo belongs to. */
  items: WorkItemRecord[];
  root: RefObject<HTMLElement | null>;
  mounted: RefObject<boolean>;
}) {
  const [overrides, setOverrides] = useState<Record<string, Override>>({});
  // The changes still offered as Undo, one per row (UNDO_MS each), by row key.
  const [undos, setUndos] = useState<Record<string, AgendaUndo>>({});
  // Rows a triage move changed: they stay in place, muted, with their date choices off, until the list is read again.
  const [triaged, setTriaged] = useState<Record<string, boolean>>({});
  // A row marked done whose Undo has run out leaves its group (it stood on under "Försenade (4)" as a fifth row
  // without "Klar"): first `leaving` (its height, for the 200 ms fold), then `left`, until the list is read again or the
  // Task is open again.
  const [leaving, setLeaving] = useState<Record<string, number>>({});
  const [left, setLeft] = useState<Record<string, boolean>>({});
  // The latest `left`, updated at once, so a queued write knows whether its row had left when the write is made.
  const leftRef = useRef<Record<string, boolean>>({});
  // The latest overrides and triage marks, updated at once, so a queued write reads what the one before it left.
  const overridesRef = useRef<Record<string, Override>>({});
  const triagedRef = useRef<Record<string, boolean>>({});
  // The fold timers of rows that leave their group (see `expire`), by row key: a read or an unmount cancels them.
  const leaveTimers = useRef(new Map<string, number>());

  useEffect(() => {
    const timers = leaveTimers.current;
    return () => {
      for (const timer of timers.values()) clearTimeout(timer);
      timers.clear();
    };
  }, []);

  function patchLeft(next: Record<string, boolean>) {
    leftRef.current = next;
    setLeft(next);
  }
  function patchTriaged(
    next: (all: Record<string, boolean>) => Record<string, boolean>,
  ) {
    triagedRef.current = next(triagedRef.current);
    setTriaged(triagedRef.current);
  }
  /** A read shows the list as it now is: no row is left or folding any more, and their timers stop. */
  function resetLeaves() {
    for (const timer of leaveTimers.current.values()) clearTimeout(timer);
    leaveTimers.current.clear();
    setLeaving({});
    patchLeft({});
  }

  /** The row as this view holds it now: the record as read, or the status and due date it last wrote. */
  function current(item: WorkItemRecord): WorkItemRecord {
    return currentWith(overrides, item);
  }
  /** The row with the latest override applied (the ref, which a queued write reads when it runs). */
  function latest(item: WorkItemRecord): WorkItemRecord {
    return currentWith(overridesRef.current, item);
  }

  function applyOverride(key: string, task: WorkTask, due: boolean) {
    // The due date the row showed before this write: a recurring Task's cycle is told from it (see afterWrite).
    const record = items.find((item) => cardKey(item) === key);
    const before = record ? latest(record).due_at : undefined;
    const next = afterWrite(overridesRef.current[key], task, due, before);
    overridesRef.current = { ...overridesRef.current, [key]: next };
    setOverrides(overridesRef.current);
    // A recorded cycle is handled like a triage move: the row stays in place with its Ångra, is not counted as
    // open, and then sinks under the group's line with "Klar · nästa: …" until the list is read again.
    if (next.cycle) patchTriaged((all) => ({ ...all, [key]: true }));
    // A Task that is open again has not left: marked done once more it waits out its own Undo first.
    if (task.status !== "completed" && leftRef.current[key]) {
      const rest = { ...leftRef.current };
      delete rest[key];
      patchLeft(rest);
    }
  }

  /** Ends the Undo of one row: its time is up, or it was used. */
  function forget(key: string) {
    setUndos((all) => {
      const rest = { ...all };
      delete rest[key];
      return rest;
    });
  }

  /**
   * The Undo of a row has run out. A row that is done then folds away (200 ms; at once with reduced motion) and leaves
   * its group; the rows above it stay where they are. When focus was in it, it goes to the next row of the group, else
   * the one before, else the group's heading.
   */
  function expire(key: string) {
    // Read before the Undo is forgotten: only a change that marked the Task done folds its row away.
    const entry = undos[key];
    forget(key);
    const record = items.find((item) => cardKey(item) === key);
    if (!entry?.completed || !record || current(record).status !== "completed")
      return;
    const row = root.current?.querySelector<HTMLElement>(
      `[data-agenda-key="${key}"]`,
    );
    const section = row?.closest("section");
    const rows = Array.from(
      section?.querySelectorAll<HTMLElement>("li[data-agenda-key]") ?? [],
    );
    const at = row ? rows.indexOf(row) : -1;
    const neighbour = rows[at + 1] ?? (at > 0 ? rows[at - 1] : undefined);
    const finish = () => {
      leaveTimers.current.delete(key);
      if (!mounted.current) return;
      setLeaving((all) => {
        const rest = { ...all };
        delete rest[key];
        return rest;
      });
      // Opened again during the fold: the row stays in its group.
      if (latest(record).status !== "completed") return;
      patchLeft({ ...leftRef.current, [key]: true });
      // Focus moves only while it is still in the row, or on nothing (the body): a focus the user took meanwhile stays.
      const active = document.activeElement;
      const inRow = Boolean(row?.contains(active));
      if (!inRow && active && active !== document.body) return;
      // After React has removed the row: the neighbour's ring or title, or the heading of the emptied group.
      requestAnimationFrame(() =>
        (
          neighbour?.querySelector<HTMLElement>(
            "button.work-agenda-glyph, .work-agenda-body > button",
          ) ?? section?.querySelector<HTMLElement>("h3")
        )?.focus({ preventScroll: true }),
      );
    };
    const still =
      typeof matchMedia === "function" &&
      matchMedia("(prefers-reduced-motion: reduce)").matches;
    if (still || !row) return finish();
    setLeaving((all) => ({ ...all, [key]: row.offsetHeight }));
    leaveTimers.current.set(key, window.setTimeout(finish, LEAVE_MS));
  }

  return {
    undos,
    triaged,
    leaving,
    left,
    current,
    latest,
    applyOverride,
    forget,
    expire,
    /** The recurring cycle the row's last write recorded, if it did (see `afterWrite`). */
    cycleOf: (key: string) => overrides[key]?.cycle,
    /** The Task version the row's last write left (for an Undo queued behind it), if it wrote. */
    versionOf: (key: string) => overridesRef.current[key]?.version,
    /** Whether the row was left or folding when it is asked (the latest value, not the last render's). */
    hasLeftNow: (key: string) => Boolean(leftRef.current[key]),
    /** Whether a triage move marked the row (the latest value, for a queued bulk move). */
    isTriagedNow: (key: string) => Boolean(triagedRef.current[key]),
    /** Remembers the Undo of a change on its row. */
    setUndo: (key: string, entry: AgendaUndo) =>
      setUndos((all) => ({ ...all, [key]: entry })),
    /** Sets or clears the triage mark of a row. */
    markTriaged: (key: string, value: boolean) =>
      patchTriaged((all) => ({ ...all, [key]: value })),
    /** Puts a row back in Klar idag (an Undo that made it done again, or a fold that ended). */
    markLeft: (key: string) => patchLeft({ ...leftRef.current, [key]: true }),
    /** A read shows the list as it now is: no triage mark, no folding or left rows any more. */
    resetForRead: () => {
      patchTriaged(() => ({}));
      resetLeaves();
    },
  };
}
