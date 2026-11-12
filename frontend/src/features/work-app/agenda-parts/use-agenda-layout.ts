import { useState } from "react";
import type { RowQueue } from "../../mcp-apps/ui/row-queue";
import type { WorkItemRecord } from "../transport";
import {
  agendaSections,
  cardKey,
  frameFor,
  type AgendaBucket,
} from "../work-items";
import { oldestFirst } from "./agenda-helpers";
import type { RowState } from "./use-row-state";

/** The caller's controls of the fullscreen shell, which keeps the filter text and the read-again counter outside the agenda. */
export type AgendaControls = {
  query: string;
  refreshTick: number;
  /** Empties the caller's search; "Rensa sökningen" under a search with no hit calls it. */
  clear?: () => void;
};

/** The filter text: the caller's when the shell keeps it, else the agenda's own. */
export function useAgendaQuery(controls: AgendaControls | undefined) {
  // The agenda's own filter text, used when the shell keeps none.
  const [ownQuery, setQuery] = useState("");
  const query = controls ? controls.query : ownQuery;
  const clearSearch = controls ? controls.clear : () => setQuery("");
  return { query, setQuery, clearSearch };
}

/**
 * What the agenda shows from the page it read: the records the filter keeps, their groups, the rows of each group in
 * the order they are shown (with those that left or wait for a decision apart), "Klar idag", and the records j and k
 * step through.
 */
export function useAgendaLayout({
  items,
  query,
  now,
  locale,
  waitingView,
  rows,
  rowQueue,
}: {
  items: WorkItemRecord[];
  query: string;
  now: Date;
  locale: string;
  waitingView: boolean;
  rows: RowState;
  rowQueue: RowQueue;
}) {
  const { current, left, undos, leaving, triaged } = rows;
  const needle = query.trim().toLocaleLowerCase();
  const visible = needle
    ? items.filter((item) => item.title.toLocaleLowerCase().includes(needle))
    : items;
  const sections = agendaSections(visible, now, locale);

  /** A done row whose Undo ran out has left its group (it shows again once the Task is open again). */
  function hasLeft(item: WorkItemRecord) {
    return Boolean(left[cardKey(item)]) && current(item).status === "completed";
  }
  /**
   * A row whose change can still be undone stands where it was, and counts as it did: its Undo shows, its fold runs, or
   * its write (the change, or its Undo) is still on its way.
   */
  function holds(item: WorkItemRecord) {
    const key = cardKey(item);
    return (
      undos[key] !== undefined ||
      leaving[key] !== undefined ||
      rowQueue.pending(key) > 0
    );
  }
  /**
   * A row of Försenade still to deal with: not done, and not moved by a triage choice, or still within its Undo. The
   * count of the group is these rows, so it changes when the Undo has run out (and a done row has folded), not on the tap.
   */
  function isOpen(item: WorkItemRecord) {
    return (
      holds(item) ||
      (current(item).status !== "completed" && !triaged[cardKey(item)])
    );
  }

  /**
   * The rows of a group in the order they are shown. Försenade counts its open rows, and shows them first, oldest
   * first; a row done or moved from it stands on its place for its Undo and then sinks under a
   * line at the group's end, so the rows above the line are the count. The other groups keep their
   * rows where they are.
   */
  function shown(section: (typeof sections)[number]) {
    const stays = section.items.filter((item) => !hasLeft(item));
    if (section.group !== "overdue")
      return { open: stays, handled: [] as WorkItemRecord[] };
    const ordered = oldestFirst(stays);
    return {
      open: ordered.filter(isOpen),
      handled: ordered.filter((item) => !isOpen(item)),
    };
  }

  /**
   * "Klar idag": the rows marked done in this view whose Undo has run out and that have folded away, in the order they
   * left. The agenda data holds only the open Tasks it was read with, so this is what the client knows: rows done here
   * since the last read. Where the data carries no more, the fallback
   * applies: no earlier completions are listed and the row's line says "Klar · finns i Status". No call is
   * made for it.
   */
  const doneToday: { record: WorkItemRecord; group: AgendaBucket }[] =
    waitingView
      ? []
      : Object.keys(left).flatMap((key) => {
          const group = sections.find((section) =>
            section.items.some((item) => cardKey(item) === key),
          );
          const record = group?.items.find((item) => cardKey(item) === key);
          return group && record && hasLeft(record)
            ? [{ record, group: group.group }]
            : [];
        });
  // The records j and k step through: those with a frame, in the order they are shown.
  const stepping = sections
    .flatMap((section) => {
      const shownRows = shown(section);
      return [...shownRows.open, ...shownRows.handled];
    })
    .filter((item) => frameFor(item) !== undefined);

  return { visible, sections, shown, doneToday, stepping };
}
