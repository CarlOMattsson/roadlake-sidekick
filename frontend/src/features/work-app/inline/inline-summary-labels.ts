import {
  contactsRoomLabelsEn,
  contactsRoomLabelsSv,
} from "../contacts/contacts-room-labels";
import {
  hierarchyDetailLabelsEn,
  hierarchyDetailLabelsSv,
} from "../hierarchy/hierarchy-detail-labels";
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
  /** A Project's target date: `target` and the date, the room's own word. */
  target: "Target date",
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
  /** After "Open Agenda · ", "Open Projects · ", "Open contacts · ": every row of the view the card leaves out,
   * "7 more". With another page to read (`more`) the count is a floor, "7+ more", never an exact number. */
  moreRows: (hidden: number, more = false) =>
    hidden > 0 ? `${hidden}${more ? "+" : ""} more` : "",
  agendaEmpty: "Nothing overdue or due today.",
  /** The empty card of a room, in the words of its full view: what is missing, what the room is for, and the
   * one sentence to say to Claude. Contacts without a match have a sentence of their own. */
  blank: {
    agenda: {
      title: workEn.agendaEmpty,
      hint: workEn.agendaEmptyHint,
      example: workEn.workEmptyAsk,
    },
    hierarchy: {
      title: workEn.hierarchyEmpty,
      hint: hierarchyDetailLabelsEn.emptyHint,
      example: hierarchyDetailLabelsEn.emptyAsk,
    },
    contacts: {
      title: workEn.noAnyContacts,
      hint: contactsRoomLabelsEn.emptyHint,
      example: contactsRoomLabelsEn.emptyAsk,
    },
  },
  noContactMatches: workEn.noContactMatches,
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
  /** Opens a summary's full view: "Show all", "Open task", "Open project", "Open contact". */
  open: "Open",
  /** The foot of a list card; its title already says how many ("12 contacts"), so the button does not repeat it. */
  showAll: "Show all",
  /** The Open button of the agenda card; the counts stand in its kicker. */
  openAgenda: "Open Agenda",
  /** The Open links of the Projects and Contacts cards: they open that view in fullscreen. */
  openHierarchy: "Open Projects",
  openContacts: "Open contacts",
  showTask: "Open task",
  showProject: "Open project",
  showContact: "Open contact",
  /** The nicknames of a Contact on its card: "Also known as Bob, Bobby". */
  alsoKnownAs: (names: string) => `Also known as ${names}`,
  /** The Done action on a Task summary, and the notices around it. */
  complete: workEn.markDone,
  completing: "Saving…",
  completedNote: "Marked the task as done.",
  /** After Done: "Done" and Undo for a short while; Undo writes the earlier status back. */
  undo: workEn.agendaUndo,
  undoneNote: "Undone. The task is open again.",
  conflict: workEn.conflict,
  /** The Done or its Undo could not be written; the line says which change failed. */
  doneFailed: "Couldn’t mark it as done.",
  undoFailed: "Couldn’t undo.",
  /** A change to a record that no longer exists: no Try again, since it cannot come back. */
  notFound: "This no longer exists. It may have been deleted elsewhere.",
  /** A Task, Project or Contact that is gone when it is read: a calm line, with no Try again. */
  goneTask: "This task no longer exists",
  goneProject: "This project no longer exists",
  goneContact: "This contact no longer exists",
  reread: "Refresh",
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
  /** A Task past its due date, as the detail line: overdue and the due date. */
  overdueSince: "Försenad sedan",
  target: "Måldatum",
  stepsOf: (done: number, total: number) => `${done} av ${total} steg`,
  tasksDoneOf: (done: number, total: number) =>
    `${done} av ${total} uppgifter klara`,
  overdueTasks: (count: number) => `${count} försenade`,
  priority: { high: "Hög", urgent: "Brådskande" },
  priorityLabel: workSv.priority,
  contacts: "Kontakter",
  /** The agenda card's title, the groups in the list's order: the today and overdue counts;
   * a `more` suffix when the read is partial. */
  agendaTitle: (overdue: number, today: number, more: boolean) =>
    [
      ...(today ? [`${today} idag`] : []),
      ...(overdue
        ? [`${overdue} ${overdue === 1 ? "försenad" : "försenade"}`]
        : []),
      ...(more ? ["fler finns"] : []),
    ].join(", "),
  /** Under the empty sentence, when other groups have records: the upcoming count, and that more exist. */
  agendaRest: (upcoming: number, more: boolean) =>
    [
      ...(upcoming ? [`${upcoming} kommande`] : []),
      ...(more ? ["fler på agendan"] : []),
    ].join(", "),
  /** After the open-room label and a separator: every row of the view the card does not
   * show. When there is another page to read (`more`) the count is a floor, never an exact number. */
  moreRows: (hidden: number, more = false) =>
    hidden > 0 ? `${hidden}${more ? "+" : ""} fler` : "",
  agendaEmpty: "Inget försenat och inget för idag.",
  blank: {
    agenda: {
      title: workSv.agendaEmpty,
      hint: workSv.agendaEmptyHint,
      example: workSv.workEmptyAsk,
    },
    hierarchy: {
      title: workSv.hierarchyEmpty,
      hint: hierarchyDetailLabelsSv.emptyHint,
      example: hierarchyDetailLabelsSv.emptyAsk,
    },
    contacts: {
      title: workSv.noAnyContacts,
      hint: contactsRoomLabelsSv.emptyHint,
      example: contactsRoomLabelsSv.emptyAsk,
    },
  },
  noContactMatches: workSv.noContactMatches,
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
  /** The Contact list without a search: the count of contacts, with a + when more exist. */
  contactCount: (count: number, more: boolean) =>
    `${count}${more ? "+" : ""} ${count === 1 && !more ? "kontakt" : "kontakter"}`,
  progressOf: (done: number, total: number) => `${done} av ${total} klara`,
  loading: "Laddar…",
  empty: "Inget att visa.",
  retry: "Försök igen",
  open: "Öppna",
  showAll: "Visa alla",
  /** The `open` button on the agenda card; the counts stand in the kicker. */
  openAgenda: "Öppna Agenda",
  openHierarchy: "Öppna Projekt",
  openContacts: "Öppna kontakterna",
  showTask: "Öppna uppgiften",
  showProject: "Öppna projektet",
  showContact: "Öppna kontakten",
  alsoKnownAs: (names) => `Även kallad ${names}`,
  complete: workSv.markDone,
  completing: "Sparar…",
  completedNote: "Markerade uppgiften som klar.",
  undo: workSv.agendaUndo,
  undoneNote: "Ångrat. Uppgiften är öppen igen.",
  conflict:
    "Uppgiften ändrades någon annanstans. Uppdatera för att se den senaste versionen.",
  doneFailed: "Kunde inte markera som klar.",
  undoFailed: "Kunde inte ångra.",
  /** A change to something that no longer exists: no `retry`, since it will not come back. */
  notFound: "Den finns inte längre. Den kan ha tagits bort någon annanstans.",
  /** A Task, Project or Contact that no longer exists when it is read: a calm line, without `retry`. */
  goneTask: "Uppgiften finns inte längre",
  goneProject: "Projektet finns inte längre",
  goneContact: "Kontakten finns inte längre",
  reread: "Uppdatera",
};

/** Summary labels for a host locale; anything that is not Swedish gets English, as in the Work app. */
export function inlineSummaryLabelsFor(locale: string): InlineSummaryLabels {
  return locale.startsWith("sv")
    ? inlineSummaryLabelsSv
    : inlineSummaryLabelsEn;
}
