import { workEn, workSv } from "../shared/labels";

/**
 * Labels for the inline Work summaries (one Task or Project, and the agenda, hierarchy and Contact list
 * counts). Kept in this file, not in @/i18n, so the MCP App bundle does not pull in the Sidekick app
 * catalogue. Words the Task room already has (Mark as done, Undo, Priority) are taken from its labels, so the card and
 * the room never say the same thing in two ways. The Swedish and English key sets must stay identical;
 * inline-summary.test.tsx checks that.
 */
export const inlineSummaryLabelsEn = {
  dateLocale: "en-GB",
  /** The eyebrow of a list summary (the app's name above the card's sentence). */
  appName: "Work",
  kind: {
    task: "Task",
    project: "Project",
    agenda: "Agenda",
    hierarchy: "Projects",
    contacts: "Contacts",
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
  due: "Due",
  /** A Task past its due date, as the detail line: "Overdue since fri 30 Oct". */
  overdueSince: "Overdue since",
  /** A Project's target date: "Target: Tue 15 Dec". */
  target: "Target",
  /** A Task's steps: "2 of 4 steps". */
  stepsOf: (done: number, total: number) => `${done} of ${total} steps`,
  /** A Project's Tasks done: "3 of 12 tasks done". */
  tasksDoneOf: (done: number, total: number) =>
    `${done} of ${total} tasks done`,
  overdueTasks: (count: number) => `${count} overdue`,
  /** Priority words shown on a Task summary; normal and low are not shown. */
  priority: { high: "High", urgent: "Urgent" },
  /** The word before a priority level: "Priority: High". */
  priorityLabel: workEn.priority,
  contacts: "Contacts",
  /** The agenda card's title, its groups in the list's order: "1 today, 2 overdue", "1 today";
   * ", more not shown" when the read is partial. */
  agendaTitle: (overdue: number, today: number, more: boolean) =>
    [
      ...(today ? [`${today} today`] : []),
      ...(overdue ? [`${overdue} overdue`] : []),
      ...(more ? ["more not shown"] : []),
    ].join(", "),
  /** Under the empty sentence, when other groups have records: "3 upcoming", "3 upcoming, more exist". */
  agendaRest: (upcoming: number, more: boolean) =>
    [
      ...(upcoming ? [`${upcoming} upcoming`] : []),
      ...(more ? ["more on the agenda"] : []),
    ].join(", "),
  /** After "Open Agenda · ": every row of the Agenda the card leaves out, "7 more". With another page
   * to read (`more`) the count is a floor, "7+ more", never an exact number. */
  agendaHidden: (hidden: number, more = false) =>
    hidden > 0 ? `${hidden}${more ? "+" : ""} more` : "",
  agendaEmpty: "Nothing overdue or due today.",
  /** The label before the agenda card's first overdue row, after today's. */
  agendaOverdueLabel: "Overdue",
  /** The label over today's rows when overdue rows follow them. */
  agendaTodayLabel: "Today",
  projectCount: "Projects",
  processCount: "Processes",
  taskCount: "Tasks",
  /** The Projects of a hierarchy as a sentence: "15 projects", "1 project", "15+ projects". */
  projectsCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "project" : "projects"}`,
  /** The Processes of a hierarchy as a sentence: "2 processes", "1 process", "2+ processes". */
  processesCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "process" : "processes"}`,
  /** The Tasks of a hierarchy as a sentence: "30 tasks", "1 task". */
  tasksCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "task" : "tasks"}`,
  matchCount: "Matches",
  /** The Contact list without a search: "3 contacts", "1 contact", "25+ contacts" when more exist. */
  contactCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "contact" : "contacts"}`,
  progressOf: (done: number, total: number) => `${done} of ${total} done`,
  loading: "Loading…",
  empty: "Nothing to show.",
  retry: "Try again",
  /** Opens a summary's full view: "Show all", "Show task", "Show project", "Show more" on a Task. */
  open: "Open",
  /** The foot of a list card; its title already says how many ("12 contacts"), so the button does not repeat it. */
  showAll: "Show all",
  /** The Open button of the agenda card; the counts stand in its kicker. */
  openAgenda: "Open Agenda",
  showMore: "Show more",
  showTask: "Show task",
  showProject: "Show project",
  /** The Done action on a Task summary, and the notices around it. */
  complete: workEn.markDone,
  completing: "Saving…",
  completedNote: "Marked the task as done.",
  /** After Done: "Done" and Undo for a short while; Undo writes the earlier status back. */
  undo: workEn.agendaUndo,
  undoneNote: "Undone. The task is open again.",
  conflict: workEn.conflict,
  saveFailed: "Couldn’t save. Try again.",
  /** A change to a record that no longer exists: no Try again, since it cannot come back. */
  notFound: "This no longer exists. It may have been deleted elsewhere.",
  /** A Task, Project or Contact that is gone when it is read: a calm line, with no Try again. */
  goneTask: "This task no longer exists",
  goneProject: "This project no longer exists",
  goneContact: "This contact no longer exists",
  reread: "Reload",
};

export type InlineSummaryLabels = typeof inlineSummaryLabelsEn;

export const inlineSummaryLabelsSv: InlineSummaryLabels = {
  dateLocale: "sv-SE",
  appName: "Arbete",
  kind: {
    task: "Uppgift",
    project: "Projekt",
    agenda: "Agenda",
    hierarchy: "Projekt",
    contacts: "Kontakter",
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
  due: "Klart senast",
  /** A Task past its due date, as the detail line: "Försenad sedan fre 30 okt". */
  overdueSince: "Försenad sedan",
  target: "Mål",
  stepsOf: (done: number, total: number) => `${done} av ${total} steg`,
  tasksDoneOf: (done: number, total: number) =>
    `${done} av ${total} uppgifter klara`,
  overdueTasks: (count: number) => `${count} försenade`,
  priority: { high: "Hög", urgent: "Brådskande" },
  priorityLabel: workSv.priority,
  contacts: "Kontakter",
  /** The agenda card's title, the groups in the list's order: "1 idag, 2 försenade", "1 idag";
   * ", fler finns" when the read is partial. */
  agendaTitle: (overdue: number, today: number, more: boolean) =>
    [
      ...(today ? [`${today} idag`] : []),
      ...(overdue
        ? [`${overdue} ${overdue === 1 ? "försenad" : "försenade"}`]
        : []),
      ...(more ? ["fler finns"] : []),
    ].join(", "),
  /** Under the empty sentence, when other groups have records: "3 kommande", "3 kommande, fler på agendan". */
  agendaRest: (upcoming: number, more: boolean) =>
    [
      ...(upcoming ? [`${upcoming} kommande`] : []),
      ...(more ? ["fler på agendan"] : []),
    ].join(", "),
  /** After "Öppna Agenda · ": every Agenda row the card does not show, "7 fler". When there is another page
   * to read (`more`) the count is a floor, "7+ fler", never an exact number. */
  agendaHidden: (hidden: number, more = false) =>
    hidden > 0 ? `${hidden}${more ? "+" : ""} fler` : "",
  agendaEmpty: "Inget försenat och inget för idag.",
  agendaOverdueLabel: "Försenade",
  agendaTodayLabel: "Idag",
  projectCount: "Projekt",
  processCount: "Processer",
  taskCount: "Uppgifter",
  projectsCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} projekt`,
  processesCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "process" : "processer"}`,
  tasksCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "uppgift" : "uppgifter"}`,
  matchCount: "Träffar",
  /** The Contact list without a search: "3 kontakter", "1 kontakt", "25+ kontakter" when more exist. */
  contactCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "kontakt" : "kontakter"}`,
  progressOf: (done: number, total: number) => `${done} av ${total} klara`,
  loading: "Laddar…",
  empty: "Inget att visa.",
  retry: "Försök igen",
  open: "Öppna",
  showAll: "Visa alla",
  /** The "Öppna" button on the agenda card; the counts stand in the kicker. */
  openAgenda: "Öppna Agenda",
  showMore: "Visa mer",
  showTask: "Visa uppgiften",
  showProject: "Visa projektet",
  complete: workSv.markDone,
  completing: "Sparar…",
  completedNote: "Markerade uppgiften som klar.",
  undo: workSv.agendaUndo,
  undoneNote: "Ångrade: uppgiften är inte längre markerad som klar.",
  conflict:
    "Uppgiften ändrades någon annanstans. Läs om för att se senaste versionen.",
  saveFailed: "Kunde inte spara. Försök igen.",
  /** A change to something that no longer exists: no "Försök igen", since it will not come back. */
  notFound: "Den finns inte längre. Den kan ha tagits bort någon annanstans.",
  /** A Task, Project or Contact that no longer exists when it is read: a calm line, without "Försök igen". */
  goneTask: "Uppgiften finns inte längre",
  goneProject: "Projektet finns inte längre",
  goneContact: "Kontakten finns inte längre",
  reread: "Läs om",
};

/** Summary labels for a host locale; anything that is not Swedish gets English, as in the Work app. */
export function inlineSummaryLabelsFor(locale: string): InlineSummaryLabels {
  return locale.startsWith("sv")
    ? inlineSummaryLabelsSv
    : inlineSummaryLabelsEn;
}
