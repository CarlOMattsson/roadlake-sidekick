import type { WorkStep, WorkStepPage } from "./transport";

/**
 * Pages read on their own before the view stops and offers "Show more steps". Ten pages of 100 are
 * the most one reorder covers (MAX_REORDER_STEPS on the server), so a Task within that limit is
 * read to its end and can be moved as a whole.
 */
export const AUTO_STEP_PAGES = 10;

export type StepRead = {
  items: WorkStep[];
  /** Where the next page starts; undefined once the Task's last Step has been read. */
  cursor: string | undefined;
  /** True when a page after the first could not be read; the pages before it are kept. */
  failed: boolean;
};

/** Adds `page` after `known`, leaving out Steps already held (a write between two reads can repeat one). */
export function appendSteps(known: WorkStep[], page: WorkStep[]): WorkStep[] {
  const seen = new Set(known.map((step) => step.id));
  return [...known, ...page.filter((step) => !seen.has(step.id))];
}

/**
 * Reads a Task's Steps from the first page, following `next_cursor` for up to `pages` pages. A
 * failure on the first page throws; a later one keeps what was read and says so. Resolves
 * undefined as soon as `isCurrent` turns false: the caller has moved on and the answer is old.
 */
export async function readSteps(
  read: (cursor?: string) => Promise<WorkStepPage>,
  isCurrent: () => boolean,
  pages: number = AUTO_STEP_PAGES,
): Promise<StepRead | undefined> {
  const first = await read();
  if (!isCurrent()) return undefined;
  let items = first.items;
  let cursor = first.next_cursor ?? undefined;
  for (let count = 1; cursor && count < pages; count++) {
    try {
      const page = await read(cursor);
      if (!isCurrent()) return undefined;
      items = appendSteps(items, page.items);
      cursor = page.next_cursor ?? undefined;
    } catch {
      return isCurrent() ? { items, cursor, failed: true } : undefined;
    }
  }
  return { items, cursor, failed: false };
}
