/**
 * Labels for the compact Work card. Kept in this file, not in labels.ts and not in @/i18n, so the
 * MCP App bundle does not pull in the Sidekick app catalogue. The Swedish and English key sets must
 * stay identical; work-card.test.tsx checks that.
 */
export const cardLabelsEn = {
  /** The card's sentence title is this word and the count: "Changes (2)". */
  title: "Changes",
  /** The eyebrow above the title: the app's name. */
  appName: "Work",
  loading: "Loading…",
  empty: "Nothing to show.",
  retry: "Try again",
  open: "Open",
  /** The Open button of the changes list: "Show all (30)". */
  showAll: "Show all ({count})",
  edit: "Edit",
  connections: "Links",
  statusGroup: "Change status",
  statusConflict:
    "This task was changed elsewhere. Reload to see the latest version.",
  reread: "Reload",
  statusFailed: "Couldn’t save the status.",
  /** A change to a Task that no longer exists: no Try again, since it cannot come back. */
  notFound: "This no longer exists. It may have been deleted elsewhere.",
  /** A Contact that is gone when it is read: calm, with no Try again. */
  goneContact: "This contact no longer exists",
  statusChanged: "Changed the status of 1 task to {status}.",
  superseded: "Replaced by a newer card",
  summaryMovedOne: "{count} task, now {status}",
  summaryMovedOther: "{count} tasks, now {status}",
  more: "+{count} more",
  kind: {
    task: "Task",
    project: "Project",
    contact: "Contact",
  },
  taskStatus: {
    todo: "To do",
    in_progress: "In progress",
    blocked: "Blocked",
    completed: "Done",
  },
  projectStatus: {
    active: "Active",
    paused: "Paused",
    completed: "Completed",
  },
};

export type CardLabels = typeof cardLabelsEn;

export const cardLabelsSv: CardLabels = {
  /** The heading is the word and the count: "Ändringar (2)". */
  title: "Ändringar",
  appName: "Arbete",
  loading: "Laddar…",
  empty: "Inget att visa.",
  retry: "Försök igen",
  open: "Öppna",
  showAll: "Visa alla ({count})",
  edit: "Redigera",
  connections: "Kopplingar",
  statusGroup: "Ändra status",
  statusConflict:
    "Uppgiften ändrades någon annanstans. Ladda om för att se den senaste versionen.",
  reread: "Ladda om",
  statusFailed: "Kunde inte spara statusen.",
  /** A change to something that no longer exists: no "Försök igen", since it will not come back. */
  notFound: "Den finns inte längre. Den kan ha tagits bort någon annanstans.",
  /** A Contact that no longer exists when it is read: calm, without "Försök igen". */
  goneContact: "Kontakten finns inte längre",
  statusChanged: "Ändrade status på 1 uppgift till {status}.",
  superseded: "Ersatt av ett nyare kort",
  summaryMovedOne: "{count} uppgift, nu {status}",
  summaryMovedOther: "{count} uppgifter, nu {status}",
  more: "+{count} fler",
  kind: {
    task: "Uppgift",
    project: "Projekt",
    contact: "Kontakt",
  },
  taskStatus: {
    todo: "Att göra",
    in_progress: "Pågår",
    blocked: "Blockerad",
    completed: "Klar",
  },
  projectStatus: {
    active: "Aktivt",
    paused: "Pausat",
    completed: "Avslutat",
  },
};

/** Card labels for a host locale; anything that is not Swedish gets English, as in the Work app. */
export function cardLabelsFor(locale: string): CardLabels {
  return locale.startsWith("sv") ? cardLabelsSv : cardLabelsEn;
}
