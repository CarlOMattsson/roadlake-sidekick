import { knownLabel } from "../shared/labels";

/**
 * Words of the agenda that no other view shares: the group headings, the filter and its empty search, the lines
 * under a row (a Step whose Task is done, a recurring Task marked done, where a Task went), the fold of Tasks marked
 * done here, the date choices of a row's menu, and the Undo line while a move is written. The shared words (Undo,
 * the empty agenda, the glyph actions of a row) stay in shared/labels.ts. Swedish comes first and is the default; the
 * English key set must stay identical to it (agenda-labels.test.ts checks that). The word set for one locale is
 * picked with agendaLabelsFor(t.dateLocale).
 */
export const agendaLabelsSv = {
  /** The undo line while a move is written and read back; there is no "Ångra" button then. */
  moving: "Flyttar…",
  doneInStatus: "Klar · finns i Status",
  /** The meta line of a Step whose Task is done. */
  parentDone: "Uppgiften är klar",
  recurringDone: "Klar · nästa: {date}",
  recurringDoneNoDate: "Klar · upprepas",
  doneToday: "Klara här",
  doneSince: "Sedan du öppnade agendan",
  /** The visible label above the agenda's search field; it is also the field's accessible name. */
  filter: "Filtrera uppgifter",
  /** An agenda search with no match; the search text stands in quotation marks. */
  noMatch: "Inga uppgifter matchar ”{q}”.",
  /** Text button under a search with no match: empties the search field. */
  clearSearch: "Rensa sökningen",
  /** Triage: moves an overdue Task to 23:59 tomorrow. */
  triageTomorrow: "Imorgon",
  /** Triage: moves an overdue Task to 23:59 next Monday. */
  triageNextWeek: "Nästa vecka",
  /** Names the date choices in a Task's ⋯ menu in the agenda: "Imorgon", "Nästa vecka" and "Välj …". */
  rescheduleGroup: "Nytt datum",
  /** The date chip in a row's quick choices; the platform's date field lies invisibly over it and opens the picker for any day. */
  rescheduleChoose: "Välj datum …",
  rescheduleRow: "Datum",
  /** Agenda group headings, in display order; the dates of a group follow the heading. */
  group: {
    overdue: "Försenade",
    today: "Idag",
    thisWeek: "Denna vecka",
    nextWeek: "Nästa vecka",
    later: "Senare",
    undated: "Utan datum",
  },
};
export type AgendaLabels = typeof agendaLabelsSv;

export const agendaLabelsEn: AgendaLabels = {
  moving: "Moving…",
  doneInStatus: "Done · in Status",
  parentDone: "Task done",
  /** A recurring Task marked done: the server reopened it for its next date. Its Undo line, and its row once Undo
   *  has run out: "Done · next: Fri 27 Nov". */
  recurringDone: "Done · next: {date}",
  /** The same, when the rule gives no next date in the reply. */
  recurringDoneNoDate: "Done · repeats",
  /** The fold last in the Agenda: the Tasks marked done here since the list was read; the count follows ("Done here (2)"),
   *  and the meta line under it says what "here" is. */
  doneToday: "Done here",
  doneSince: "Since you opened the agenda",
  filter: "Filter tasks",
  /** An agenda search with no hit, naming the search text. */
  noMatch: "No tasks match “{q}”.",
  clearSearch: "Clear search",
  triageTomorrow: "Tomorrow",
  triageNextWeek: "Next week",
  rescheduleGroup: "New date",
  rescheduleChoose: "Choose date…",
  rescheduleRow: "Date",
  group: {
    overdue: "Overdue",
    today: "Today",
    thisWeek: "This week",
    nextWeek: "Next week",
    later: "Later",
    undated: "No date",
  },
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function agendaLabelsFor(dateLocale: string): AgendaLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? agendaLabelsSv
    : agendaLabelsEn;
}

/** Translated agenda group heading; a group this view does not know is shown as it arrived. */
export function agendaGroupLabel(labels: AgendaLabels, value: string): string {
  return knownLabel(labels.group, value);
}
