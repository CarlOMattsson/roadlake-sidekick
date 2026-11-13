/**
 * Words of the agenda's "move all overdue" action, spread into `workEn` and `workSv` (labels.ts): the question that
 * replaces the button, the confirming button, the line after the move beside Ångra, and the failure of the move or of
 * its Ångra. The Swedish and English key sets must stay identical (`WorkLabels` is derived from the English set).
 */
export const moveAllEn = {
  moveAllConfirm: (n: number) => `Move ${n} to tomorrow?`,
  moveAllConfirmYes: "Move",
  moveAllDone: (n: number) => `${n} moved to tomorrow`,
  moveAllFailed: "Couldn’t move the overdue tasks. Try again.",
};

export const moveAllSv: typeof moveAllEn = {
  moveAllConfirm: (n: number) => `Flytta ${n} till imorgon?`,
  moveAllConfirmYes: "Flytta",
  moveAllDone: (n: number) =>
    `${n} ${n === 1 ? "flyttad" : "flyttade"} till imorgon`,
  moveAllFailed: "Det gick inte att flytta de försenade. Försök igen.",
};
