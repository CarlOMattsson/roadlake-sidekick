/**
 * Words of the Work hierarchy that are not in labels.ts: the meta words of the Projects tab (no Tasks, open Tasks,
 * overdue, an empty Domain), the title filter, the group of completed Projects, the Task detail's date choice "Imorgon" (one word, design system §1.6), and the words of the Task and Contact detail. The shared words (Status, Description, Loading, Try again, the kind names) stay
 * in labels.ts. The word set for one locale is picked with hierarchyDetailLabelsFor(dateLocale). The
 * Swedish and English key sets must stay identical (hierarchy-detail.test.tsx checks that).
 */
export const hierarchyDetailLabelsSv = {
  /** A Project with no Tasks yet, on its meta line in the Projects tab. */
  noTasks: "Inga uppgifter än",
  /** A Process's open Tasks, on its meta line. */
  openTasks: (n: number) =>
    n === 0
      ? "Inga öppna uppgifter"
      : n === 1
        ? "1 öppen uppgift"
        : `${n} öppna uppgifter`,
  /** Overdue Tasks of a Project or Process, in the overdue tone. */
  overdue: (n: number) => `${n} ${n === 1 ? "försenad" : "försenade"}`,
  /** A Domain with no Project or Process yet, under its heading. */
  noGroups: "Inga projekt eller processer än.",
  /** The empty Projects tab: what the tab is for, and the one sentence to say to Claude (the inline card says the same). */
  emptyHint:
    "Ett projekt har ett slut, en process pågår. Båda samlar uppgifter.",
  emptyAsk: "Starta ett projekt som heter Renovera köket",
  /** The heading over the Projects and Processes outside every Domain, drawn only when there are Domains. */
  noDomain: "Utan domän",
  /** The title filter's label, the same frame as the agenda's filter. */
  filter: "Filtrera projekt och processer",
  /** Shown instead of the tree when the title filter matches nothing. */
  noMatches: "Inga träffar i filtret.",
  /** Shown instead of noMatches while more Projects can be loaded: the filter only reads the ones already loaded. */
  noMatchesLoaded:
    "Inga träffar bland de laddade projekten. Visa fler för att söka vidare.",
  /** The closed group of completed Projects, last in the tree. */
  completedGroup: (count: number) => `Avslutade (${count})`,
  dueTomorrow: "Imorgon",
  /** The Task's status chip (design system §3, egenskapschip): its name is "Ändra status: Att göra". */
  changeStatus: "Ändra status",
  /** The Task's priority chip: its name is "Ändra prioritet: Hög". */
  changePriority: "Ändra prioritet",
  /** The Contact's note as a paragraph under "Om Anna" (design system §3, Kontaktvyn). */
  aboutContact: (first: string) => `Om ${first}`,
  /** The closed section with e-mail, phone and address. */
  waysToReach: "Kontaktvägar",
  /** Kontaktvägar's meta line names what is there, "E-post och telefon": the words, and the locale that lists them. */
  wayWords: ["e-post", "telefon", "adress"],
  wayLocale: "sv",
  /** The create field of the Contact list: a new Contact needs only a name. */
  newContactExample: "Ny kontakt, t.ex. Anna Andersson",
  close: "Stäng",
  add: "Lägg till",
};

export type HierarchyDetailLabels = typeof hierarchyDetailLabelsSv;

export const hierarchyDetailLabelsEn: HierarchyDetailLabels = {
  noTasks: "No tasks yet",
  openTasks: (n) =>
    n === 0 ? "No open tasks" : n === 1 ? "1 open task" : `${n} open tasks`,
  overdue: (n) => `${n} overdue`,
  noGroups: "No projects or processes yet.",
  emptyHint: "A project has an end, a process goes on. Both hold tasks.",
  emptyAsk: "Start a project called Renovate the kitchen",
  noDomain: "Not in an area",
  filter: "Filter projects and processes",
  noMatches: "No matches.",
  noMatchesLoaded:
    "No matches among the loaded projects. Show more to search further.",
  completedGroup: (count) => `Completed (${count})`,
  dueTomorrow: "Tomorrow",
  changeStatus: "Change status",
  changePriority: "Change priority",
  aboutContact: (first) => `About ${first}`,
  waysToReach: "Contact details",
  wayWords: ["email", "phone", "address"],
  wayLocale: "en",
  newContactExample: "New contact, e.g. Anna Andersson",
  close: "Close",
  add: "Add",
};

/** The detail words for a work locale: Swedish for "sv-SE", English otherwise. */
export function hierarchyDetailLabelsFor(
  dateLocale: string,
): HierarchyDetailLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? hierarchyDetailLabelsSv
    : hierarchyDetailLabelsEn;
}
