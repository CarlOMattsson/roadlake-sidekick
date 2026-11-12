import {
  boardColumns,
  boardSegments,
  cardKey,
  foldSearchText,
  nestSteps,
  segmentItems,
  shownOrder,
  type BoardSegment,
} from "../../shared/work-items";
import type { WorkLabels } from "../../shared/labels";
import { findTaskCard, shownIn, type BoardUndo } from "../board-columns";
import type { RowQueue } from "../../../mcp-apps/ui/row-queue";
import type {
  TaskStatusValue,
  WorkBoardFrame,
  WorkItemRecord,
} from "../../transport/transport";

/** A Task dropped or stepped to another column, shown there until its write is answered. */
export type Preview = { taskId: string; column: TaskStatusValue };

type Options = {
  page: WorkBoardFrame["page"];
  labels: WorkLabels;
  single: boolean;
  needle: string;
  undos: Record<string, BoardUndo>;
  preview: Preview | undefined;
  rowQueue: RowQueue;
};

/** What the board draws: the columns or the sections of the single layout, with the search and the previews applied. */
export function useBoardSections({
  page,
  labels: t,
  single,
  needle,
  undos,
  preview,
  rowQueue,
}: Options) {
  const columns = boardColumns(page.columns);
  const anyCard = columns.some((status) => page.columns[status]?.length);
  const movingCard = preview ? findTaskCard(preview.taskId, page) : undefined;
  /** The search keeps matching titles, in both layouts: the same cards are held back whichever way the board is laid out. */
  function matchesSearch(item: WorkItemRecord) {
    return !needle || foldSearchText(item.title).includes(needle);
  }
  /**
   * The cards of one column as shown: a moving Task leaves its column and is drawn in its target. The columns are the
   * phone's sections (boardSegments): the four Task statuses and one Projekt column, so a Project status such as
   * "active" never stands as a column of its own beside the Task statuses.
   */
  function shownItems(segment: BoardSegment) {
    const shown: { item: WorkItemRecord; pending: boolean }[] = [];
    for (const item of segmentItems(page, segment)) {
      if (
        matchesSearch(item) &&
        (!movingCard || cardKey(item) !== cardKey(movingCard))
      )
        shown.push({ item, pending: false });
    }
    if (movingCard && preview?.column === segment.key)
      shown.push({
        item: { ...movingCard, status: segment.key },
        pending: true,
      });
    return shown;
  }
  const waitingCards = Object.values(page.columns)
    .flat()
    .filter((item) => rowQueue.queued(cardKey(item)));
  /** The waiting mark and busy state a card shows while its writes run. */
  function queueOf(item: WorkItemRecord) {
    const key = cardKey(item);
    return {
      queued: rowQueue.queued(key),
      busy: rowQueue.pending(key) > 0,
    };
  }
  // The single layout lists every status as a section of its own, in board order.
  // `items` are the section's records (its count), `shown` the cards it draws (see shownIn).
  const sections = single
    ? boardSegments(page, t).map((segment) => {
        const items = shownOrder(
          page,
          segment.key,
          segmentItems(page, segment).filter(matchesSearch),
        );
        return {
          segment,
          items,
          shown: nestSteps(shownIn(segment.key, items, undos, page)),
        };
      })
    : [];
  const columnSections = single
    ? []
    : boardSegments(page, t).map((segment) => ({
        segment,
        items: shownItems(segment),
      }));
  const anyShown = single
    ? sections.some(({ shown }) => shown.length)
    : columnSections.some(({ items }) => items.length);
  return {
    anyCard,
    sections,
    columnSections,
    anyShown,
    waitingCards,
    queueOf,
  };
}
