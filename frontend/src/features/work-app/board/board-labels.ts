/**
 * Words of Status (the board) that no other view shares: its empty state, the inline summary, the words of a card
 * (move up and down, the status list, dragging), and the notices that stand where a change was made: a refused
 * change, a failed change to one row, a failed "Visa fler", and the conflict notice, which the agenda and "Att sortera"
 * show too. Swedish comes first and is the default; the English key set must stay identical to it
 * (board-labels.test.ts checks that). The word set for one locale is picked with boardLabelsFor(t.dateLocale).
 */
export const boardLabelsSv = {
  /** The board's next page, after every status: it reads more Tasks of all of them. */
  showMore: "Visa fler uppgifter",
  /** A status column with no card. */
  noCards: "Inget här.",
  empty: "Inga uppgifter här än.",
  emptyHint:
    "Dina uppgifter efter status: att göra, pågår, blockerad och klar.",
  forbidden: "Du har inte behörighet att se Status.",
  openBoard: "Öppna Status",
  nearestOverdue: "Äldst försenade",
  nearest: "Närmast i tid",
  /** Under the inline board summary, and last in the text to the model, when the page has more records. */
  more: "Fler finns",
  /** The inline board summary's one line for records the nearest-due list does not show; {count} is the number. */
  hiddenCount: "{count} fler",
  headline: (overdue: number, open: number, more: boolean) => {
    const plus = more ? "+" : "";
    return overdue
      ? `${overdue}${plus} försenad${overdue > 1 ? "e" : ""} av ${open}${plus} öppna`
      : `${open}${plus} öppna`;
  },
  /** Moves a card one place up in its Task status column. */
  moveUp: "Flytta upp",
  /** Moves a card one place down in its Task status column. */
  moveDown: "Flytta ned",
  moveListFor: (title: string) => `Välj status för ${title}`,
  dragTaskFor: (title: string) =>
    `Dra ${title}, eller använd vänster- och högerpilen för att flytta till kolumnen bredvid`,
  moveFailed: "Det gick inte att ändra status.",
  rowChangeFailed: (title: string) => `Det gick inte att ändra ”${title}”.`,
  moreFailed: "Det gick inte att hämta fler.",
  /** A refused change on the board, the agenda or "Att sortera": the text names no view, since all three show it. */
  conflict: "Listan har lästs om, försök igen.",
  conflictAction: "Hämta senaste",
};
export type BoardLabels = typeof boardLabelsSv;

export const boardLabelsEn: BoardLabels = {
  showMore: "Show more tasks",
  noCards: "Nothing here.",
  empty: "No tasks yet.",
  /** The empty Status: what the view is for, under "No tasks yet." */
  emptyHint: "Your tasks by status: to do, in progress, blocked, and done.",
  forbidden: "You don’t have access to Status.",
  openBoard: "Open Status",
  nearestOverdue: "Longest overdue",
  nearest: "Due soonest",
  more: "More not shown",
  hiddenCount: "{count} more",
  /** The inline board card's title: "5 overdue of 13 open", "13 open" with none overdue; "+" after the counts while more pages exist. */
  headline: (overdue: number, open: number, more: boolean) => {
    const plus = more ? "+" : "";
    return overdue
      ? `${overdue}${plus} overdue of ${open}${plus} open`
      : `${open}${plus} open`;
  },
  moveUp: "Move up",
  moveDown: "Move down",
  moveListFor: (title: string) => `Choose a status for ${title}`,
  dragTaskFor: (title: string) =>
    `Drag ${title}, or use the left and right arrow keys to move it to the next column`,
  moveFailed: "Couldn’t change the status.",
  rowChangeFailed: (title: string) => `Couldn’t change “${title}”.`,
  moreFailed: "Couldn’t load more.",
  /** A refused change in the board, the agenda or To sort: the text names no view, since all three show it. */
  conflict: "The list was refreshed. Try again.",
  /** The conflict notice's button; not "Refresh", which is already the toolbar's name for the same read. */
  conflictAction: "Get the latest",
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function boardLabelsFor(dateLocale: string): BoardLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? boardLabelsSv
    : boardLabelsEn;
}
