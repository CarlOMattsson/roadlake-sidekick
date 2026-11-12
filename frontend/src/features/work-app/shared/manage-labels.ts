/**
 * Words the Work App's list controls share (move up and down, archive, restore, undo, and the four
 * ways a write is refused). Kept in this file, not in labels.ts, so the controls can be built beside
 * each other; the word set for one locale is picked with manageLabelsFor(t.dateLocale), as
 * waitingLabelsFor does. The Swedish and English key sets must stay identical (manage-controls.test.tsx).
 */
export const manageLabelsEn = {
  up: "Up",
  down: "Down",
  archive: "Archive",
  restore: "Restore",
  undo: "Undo",
  removeLink: "Remove link",
  reload: "Reload",
  retry: "Try again",
  moveUpFor: (title: string) => `Move up: ${title}`,
  moveDownFor: (title: string) => `Move down: ${title}`,
  archiveFor: (title: string) => `Archive: ${title}`,
  restoreFor: (title: string) => `Restore: ${title}`,
  archivedHeading: (count: number) => `Archived (${count})`,
  moved: (title: string, place: number, total: number) =>
    `Moved “${title}” to position ${place} of ${total}.`,
  archived: (title: string) => `Archived “${title}”.`,
  restored: (title: string) => `Restored “${title}”.`,
  conflict:
    "This was changed elsewhere after you loaded it. Reload to see the latest, then try again.",
  forbidden: "You don’t have permission to make this change.",
  notFound: "This no longer exists. It may have been deleted in another chat.",
  invalid: "That change wasn’t accepted. Reload and try again.",
  failed: "Couldn’t save the change.",
};
export type ManageLabels = typeof manageLabelsEn;

export const manageLabelsSv: ManageLabels = {
  up: "Upp",
  down: "Ned",
  archive: "Arkivera",
  restore: "Återställ",
  undo: "Ångra",
  removeLink: "Ta bort koppling",
  reload: "Läs om",
  retry: "Försök igen",
  moveUpFor: (title) => `Flytta upp: ${title}`,
  moveDownFor: (title) => `Flytta ned: ${title}`,
  archiveFor: (title) => `Arkivera: ${title}`,
  restoreFor: (title) => `Återställ: ${title}`,
  archivedHeading: (count) => `Arkiverade (${count})`,
  moved: (title, place, total) =>
    `Flyttade ”${title}” till plats ${place} av ${total}.`,
  archived: (title) => `Arkiverade ”${title}”.`,
  restored: (title) => `Återställde ”${title}”.`,
  conflict:
    "Det här ändrades någon annanstans efter att du läste det. Läs om, så ser du senaste läget, och försök sedan igen.",
  forbidden: "Du har inte behörighet att göra den här ändringen.",
  notFound: "Den finns inte längre. Den kan ha tagits bort i en annan chatt.",
  invalid: "Ändringen godtogs inte. Läs om och försök igen.",
  failed: "Ändringen kunde inte sparas.",
};

/** The shared words for a work locale: Swedish for "sv-SE", English otherwise. */
export function manageLabelsFor(dateLocale: string): ManageLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? manageLabelsSv
    : manageLabelsEn;
}
