import type { JournalDay } from "./transport";

/** A day without entries or summary, the shape the day view draws as an empty day. */
export function emptyDay(journalDate: string): JournalDay {
  return {
    journal_date: journalDate,
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: journalDate,
      exists: false,
      status: null,
      content: null,
    },
  };
}
