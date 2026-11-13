/**
 * Words of the agenda's "move all overdue" action, spread into `workEn` and `workSv` (labels.ts): the button (it
 * moves every open overdue Task to tomorrow with one call, and always states the count), the question that replaces it, the confirming button, the line after the move beside Ångra, and the failure of the move or of
 * its Ångra. It also holds the agenda's notices that stand where the action was made: a failed change to one row,
 * which names its Task, a failed "Visa fler", and the conflict notice of a refused change. The Swedish and English key sets must stay identical (`WorkLabels` is
 * derived from the English set).
 */

/** The count with its noun: "1 task", "5 tasks". */
const taskCountEn = (n: number) => `${n} ${n === 1 ? "task" : "tasks"}`;

export const moveAllEn = {
  moveAllOverdue: (n: number) =>
    `Move ${n} overdue ${n === 1 ? "task" : "tasks"} to tomorrow`,
  moveAllConfirm: (n: number) => `Move ${taskCountEn(n)} to tomorrow?`,
  moveAllConfirmYes: "Move",
  moveAllDone: (n: number) => `Moved ${taskCountEn(n)} to tomorrow`,
  moveAllFailed: "Couldn’t move the overdue tasks.",
  rowChangeFailed: (title: string) => `Couldn’t change “${title}”.`,
  moreFailed: "Couldn’t load more.",
  /** A refused change in the board, the agenda or To sort: the text names no view, since all three show it. */
  boardConflict: "The list was reloaded. Try again.",
  /** The conflict notice's button; not "Refresh", which is already the toolbar's name for the same read. */
  boardConflictAction: "Get the latest",
};

export const moveAllSv: typeof moveAllEn = {
  moveAllOverdue: (n: number) =>
    `Flytta ${n} ${n === 1 ? "försenad" : "försenade"} till imorgon`,
  moveAllConfirm: (n: number) => `Flytta ${n} till imorgon?`,
  moveAllConfirmYes: "Flytta",
  moveAllDone: (n: number) =>
    `${n} ${n === 1 ? "flyttad" : "flyttade"} till imorgon`,
  moveAllFailed: "Det gick inte att flytta de försenade.",
  rowChangeFailed: (title: string) => `Det gick inte att ändra ”${title}”.`,
  moreFailed: "Det gick inte att hämta fler.",
  /** A refused change on the board, the agenda or "Att sortera": the text names no view, since all three show it. */
  boardConflict: "Listan har lästs om, försök igen.",
  boardConflictAction: "Hämta senaste",
};
