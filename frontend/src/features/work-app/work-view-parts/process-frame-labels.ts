/**
 * Words of the Process page that are not in labels.ts. The word set for one locale is picked with
 * processFrameLabelsFor(dateLocale). The Swedish and English key sets must stay identical
 * (process-frame.test.tsx checks that).
 */
export const processFrameLabelsSv = {
  /** The kind word: the kicker of the page and its heading while the Process is not read. */
  process: "Process",
  /** Shown when the server says the Process no longer exists. */
  gone: "Processen finns inte längre",
  noTasks: "Inga uppgifter i processen.",
  tasksForbidden: "Du har inte behörighet att se processens uppgifter.",
  /** The phone's host cannot list a Process's Tasks: a calm line instead of the list. */
  tasksUnavailable: "Processens uppgifter visas inte i den här appen än.",
  /** Under the Tasks when the server cut the list and has no cursor for the rest (the phone's host). */
  tasksTruncated: "Listan är avkortad. Alla uppgifter visas inte.",
  /** The Process's declared rhythm (Cadence), on its meta line; an unknown value is shown as it is. */
  cadence: {
    daily: "Varje dag",
    weekly: "Varje vecka",
    biweekly: "Varannan vecka",
    monthly: "Varje månad",
    quarterly: "Varje kvartal",
    yearly: "Varje år",
  } as Record<string, string>,
};

export type ProcessFrameLabels = typeof processFrameLabelsSv;

export const processFrameLabelsEn: ProcessFrameLabels = {
  process: "Process",
  gone: "This process no longer exists",
  noTasks: "No tasks in this process.",
  tasksForbidden: "You don’t have access to this process’s tasks.",
  tasksUnavailable: "This app doesn’t show a process’s tasks yet.",
  tasksTruncated: "The list is cut short. Not every task is shown.",
  cadence: {
    daily: "Daily",
    weekly: "Weekly",
    biweekly: "Every two weeks",
    monthly: "Monthly",
    quarterly: "Quarterly",
    yearly: "Yearly",
  },
};

export function processFrameLabelsFor(dateLocale: string): ProcessFrameLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? processFrameLabelsSv
    : processFrameLabelsEn;
}
