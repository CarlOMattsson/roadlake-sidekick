/**
 * The texts of deleting for good in the trash view (trash-view.tsx): "Delete permanently" on a Task row and "Empty the
 * trash". They exist only where the host has the tool, which today is the phone; Claude has none. Swedish first. A
 * sentence ends with a full stop, a button without one. No text speaks of confirmation flags: the owner is asked a
 * plain question and answers it.
 */
export type EraseLabels = {
  erase: string;
  eraseLabel: (title: string) => string;
  /** The question under a row; `title` is null when the caller may not read it. */
  eraseQuestion: (title: string | null) => string;
  eraseYes: string;
  eraseNo: string;
  erasing: string;
  /** The row's receipt after a task was deleted for good, after the kind ("Task · deleted permanently"). */
  erased: string;
  /** A 409: the Task has Steps or links left, or its version moved on. */
  eraseConflict: string;
  eraseForbidden: string;
  eraseFailed: string;
  /** One line under the list: what cannot be deleted for good. */
  eraseHelp: string;
  emptyTrash: string;
  /** `more`: the list holds only the first rows read, so the count is "at least". */
  emptyQuestion: (count: number, more?: boolean) => string;
  /** The status line after emptying: what went and what had to stay. */
  emptyDone: (removed: number, kept: number) => string;
  emptyFailed: string;
};

export const eraseEn: EraseLabels = {
  erase: "Delete permanently",
  eraseLabel: (title) => `Delete ${title} permanently`,
  eraseQuestion: (title) =>
    `Delete ${title ? `“${title}”` : "this task"} permanently? This can’t be undone.`,
  eraseYes: "Delete",
  eraseNo: "Cancel",
  erasing: "Deleting…",
  erased: "deleted permanently",
  eraseConflict:
    "Can’t delete: the task still has steps or links, or it was changed. Remove them in Claude.",
  eraseForbidden: "You don’t have permission to delete this.",
  eraseFailed: "Couldn’t delete.",
  eraseHelp:
    "Journal entries and shopping items can’t be deleted permanently, only restored.",
  emptyTrash: "Empty the trash",
  emptyQuestion: (count, more = false) =>
    `Delete ${more ? "at least " : ""}${count} ${count === 1 ? "task" : "tasks"} permanently? Journal entries and shopping items stay. This can’t be undone.`,
  emptyDone: (removed, kept) =>
    `${removed} deleted${kept > 0 ? `, ${kept} couldn’t be deleted` : ""}`,
  emptyFailed: "Couldn’t empty the trash.",
};

export const eraseSv: EraseLabels = {
  erase: "Radera för gott",
  eraseLabel: (title) => `Radera ${title} för gott`,
  eraseQuestion: (title) =>
    `Radera ${title ? `”${title}”` : "uppgiften"} för gott? Det går inte att ångra.`,
  eraseYes: "Radera",
  eraseNo: "Avbryt",
  erasing: "Raderar…",
  erased: "raderad för gott",
  eraseConflict:
    "Kan inte raderas: uppgiften har steg eller länkar kvar, eller ändrades. Ta bort dem i Claude.",
  eraseForbidden: "Du saknar behörighet att radera den.",
  eraseFailed: "Det gick inte att radera.",
  eraseHelp:
    "Dagboksinlägg och varor kan inte raderas för gott, bara återställas.",
  emptyTrash: "Töm papperskorgen",
  emptyQuestion: (count, more = false) =>
    `Radera ${more ? "minst " : ""}${count} ${count === 1 ? "uppgift" : "uppgifter"} för gott? Dagboksinlägg och varor ligger kvar. Det går inte att ångra.`,
  emptyDone: (removed, kept) =>
    `${removed} ${removed === 1 ? "raderad" : "raderade"}${kept > 0 ? `, ${kept} kunde inte raderas` : ""}`,
  emptyFailed: "Det gick inte att tömma papperskorgen.",
};
