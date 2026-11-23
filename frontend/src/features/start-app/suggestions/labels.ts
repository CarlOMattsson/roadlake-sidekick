/**
 * Texts of the suggestion inbox (sv and en with equal keys). The words on the decision buttons and the check's
 * sentences are the decision family's (ui/decision-labels.ts); these are the inbox's own: its headings, its receipts,
 * the words for an effect and for the fields a suggestion would set, and where an untrusted quote comes from.
 */
type Effect = "create_task" | "create_contact";
type SourceKind =
  "mail" | "calendar" | "chat" | "web" | "api" | "share" | "sidekick";

const suggestionsEn = {
  dateLocale: "en-GB",
  title: "Suggestions",
  kicker: "Suggestion",
  /** The inline card's title over a group: "3 safe suggestions". */
  safeCount: (count: number) =>
    count === 1 ? "1 safe suggestion" : `${count} safe suggestions`,
  /** The inline card's title without a group. */
  waitingCount: (count: number) =>
    count === 1 ? "1 suggestion waits" : `${count} suggestions wait`,
  /** The section heading of a group in the full view, with the automation as its kicker. */
  safeHeading: (count: number) => `Safe suggestions (${count})`,
  reviewHeading: (count: number) => `To review (${count})`,
  fromAutomation: (name: string) => `From ${name}`,
  empty: "No suggestions right now.",
  emptyHint: "What your automations propose waits here for you to decide.",
  /** Suggestions the connection may not read (another room's scope). */
  hidden: (count: number) =>
    count === 1
      ? "1 suggestion is not shown with this connection."
      : `${count} suggestions are not shown with this connection.`,
  loadMore: "Show more",
  loadingMore: "Loading…",
  openInbox: "Open Suggestions",
  openSuggestion: "Open the suggestion",
  moreWaiting: (count: number) => `${count} more`,
  refresh: "Refresh",
  moreActions: "More actions for Suggestions",
  effects: {
    create_task: "Create task",
    create_contact: "Create contact",
  } satisfies Record<Effect, string>,
  /** The fields a suggestion sets, as the detail lists them. */
  fields: {
    due_on: "Due",
    priority: "Priority",
    project: "Project",
    description: "Description",
    email: "E-mail",
    phone: "Phone",
    organization: "Company",
    role: "Role",
    context_note: "Note",
  },
  priorities: { low: "Low", normal: "Normal", high: "High" } as Record<
    string,
    string
  >,
  /** A Project the suggestion links: the app does not read its name. */
  inAProject: "In a project",
  /** The label over untrusted text, by where it came from. */
  quoteFrom: {
    mail: "From the e-mail, not written by Sidekick",
    calendar: "From the calendar, not written by Sidekick",
    chat: "From the chat, not written by Sidekick",
    web: "From the web page, not written by Sidekick",
    api: "From the source, not written by Sidekick",
    share: "From what was shared, not written by Sidekick",
    sidekick: "From Sidekick's own records",
  } satisfies Record<SourceKind, string>,
  /** The detail's line under the card: who proposed it and until when it can be decided. */
  proposedBy: (automation: string, until: string) =>
    `Proposed by ${automation} · can be decided until ${until}`,
  /** Why a card is not in the safe group, as one line in the detail. */
  notInGroup: "Not in the safe group:",
  blockers: {
    not_pending: "it is not waiting",
    not_checked: "it is not checked",
    verdict_not_ok: "the check found something",
    below_threshold: "the check was not sure enough",
    flagged: "the screen flagged it",
    edited: "you edited it",
    not_low_risk: "the change is not low risk",
    run_not_done: "the run is not done",
  } as Record<string, string>,
  /** A suggestion that is no longer waiting, in the detail. */
  states: {
    applied: "Approved",
    dismissed: "Dismissed",
    undone: "Approved, then undone",
    expired: "Expired without a decision",
    received: "Arrived, being checked",
    checking: "Being checked",
    pending: "Waiting for you",
  } as Record<string, string>,
  /** Receipts in the bar (no full stop). */
  approved: (title: string) => `Approved: ${title}`,
  dismissed: (title: string) => `Dismissed: ${title}`,
  approvedMany: (count: number) =>
    count === 1 ? "Approved: 1 suggestion" : `Approved: ${count} suggestions`,
  undo: "Undo",
  show: "Show",
  undone: (count: number) =>
    count === 1 ? "Undone: 1 suggestion" : `Undone: ${count} suggestions`,
  undoFailed: "Could not undo: the record changed after it was created",
  /** The card's own receipt while Undo is offered. */
  addedTask: (title: string) => `Added: ${title}`,
  addedContact: (name: string) => `Added: ${name}`,
  dismissedCard: "Dismissed",
  open: "Open",
  /** Some of a group were not taken; each card says why. */
  groupPartly: (taken: number, count: number) =>
    `Approved ${taken} of ${count}. The rest wait as single cards.`,
  groupChanged: "The group changed and was read again",
  /** The receipt card inline after Claude decided. */
  decidedTitle: (approved: number, dismissed: number) =>
    [
      approved > 0
        ? approved === 1
          ? "1 approved"
          : `${approved} approved`
        : null,
      dismissed > 0
        ? dismissed === 1
          ? "1 dismissed"
          : `${dismissed} dismissed`
        : null,
    ]
      .filter(Boolean)
      .join(" · ") || "Nothing decided",
  undoneTitle: "Undone: the record is in the trash",
  refused: (count: number) =>
    count === 1 ? "1 was not taken" : `${count} were not taken`,
};

export type SuggestionLabels = typeof suggestionsEn;

const suggestionsSv: SuggestionLabels = {
  dateLocale: "sv-SE",
  title: "Förslag",
  kicker: "Förslag",
  safeCount: (count) =>
    count === 1 ? "1 säkert förslag" : `${count} säkra förslag`,
  waitingCount: (count) =>
    count === 1 ? "1 förslag väntar" : `${count} förslag väntar`,
  safeHeading: (count) => `Säkra förslag (${count})`,
  reviewHeading: (count) => `Att granska (${count})`,
  fromAutomation: (name) => `Från ${name}`,
  empty: "Inga förslag just nu.",
  emptyHint: "Det dina automationer föreslår väntar här på ditt beslut.",
  hidden: (count) =>
    count === 1
      ? "1 förslag syns inte med den här anslutningen."
      : `${count} förslag syns inte med den här anslutningen.`,
  loadMore: "Visa fler",
  loadingMore: "Hämtar…",
  openInbox: "Öppna Förslag",
  openSuggestion: "Öppna förslaget",
  moreWaiting: (count) => `${count} till`,
  refresh: "Uppdatera",
  moreActions: "Fler val för Förslag",
  effects: {
    create_task: "Skapa uppgift",
    create_contact: "Skapa kontakt",
  },
  fields: {
    due_on: "Förfaller",
    priority: "Prioritet",
    project: "Projekt",
    description: "Beskrivning",
    email: "E-post",
    phone: "Telefon",
    organization: "Företag",
    role: "Roll",
    context_note: "Anteckning",
  },
  priorities: { low: "Låg", normal: "Normal", high: "Hög" },
  inAProject: "I ett projekt",
  quoteFrom: {
    mail: "Ur mejlet, inte skrivet av Sidekick",
    calendar: "Ur kalendern, inte skrivet av Sidekick",
    chat: "Ur chatten, inte skrivet av Sidekick",
    web: "Från webbsidan, inte skrivet av Sidekick",
    api: "Ur källan, inte skrivet av Sidekick",
    share: "Ur det som delades, inte skrivet av Sidekick",
    sidekick: "Ur Sidekicks egna uppgifter",
  },
  proposedBy: (automation, until) =>
    `Föreslaget av ${automation} · kan beslutas till ${until}`,
  notInGroup: "Inte bland de säkra:",
  blockers: {
    not_pending: "det väntar inte",
    not_checked: "det är inte kontrollerat",
    verdict_not_ok: "kontrollen hittade något",
    below_threshold: "kontrollen var inte säker nog",
    flagged: "granskningen flaggade det",
    edited: "du har ändrat det",
    not_low_risk: "ändringen är inte lågrisk",
    run_not_done: "körningen är inte klar",
  },
  states: {
    applied: "Godkänt",
    dismissed: "Avböjt",
    undone: "Godkänt och sedan ångrat",
    expired: "Gick ut utan beslut",
    received: "Har kommit, kontrolleras",
    checking: "Kontrolleras",
    pending: "Väntar på dig",
  },
  approved: (title) => `Godkänt: ${title}`,
  dismissed: (title) => `Avböjt: ${title}`,
  approvedMany: (count) =>
    count === 1 ? "Godkänt: 1 förslag" : `Godkända: ${count} förslag`,
  undo: "Ångra",
  show: "Visa",
  undone: (count) =>
    count === 1 ? "Ångrat: 1 förslag" : `Ångrade: ${count} förslag`,
  undoFailed: "Kunde inte ångra: posten har ändrats sedan den skapades",
  addedTask: (title) => `Tillagd: ${title}`,
  addedContact: (name) => `Tillagd: ${name}`,
  dismissedCard: "Avböjt",
  open: "Öppna",
  groupPartly: (taken, count) =>
    `Godkände ${taken} av ${count}. Resten väntar som enskilda kort.`,
  groupChanged: "Gruppen har ändrats och är hämtad igen",
  decidedTitle: (approved, dismissed) =>
    [
      approved > 0
        ? approved === 1
          ? "1 godkänt"
          : `${approved} godkända`
        : null,
      dismissed > 0
        ? dismissed === 1
          ? "1 avböjt"
          : `${dismissed} avböjda`
        : null,
    ]
      .filter(Boolean)
      .join(" · ") || "Inget beslutat",
  undoneTitle: "Ångrat: posten ligger i papperskorgen",
  refused: (count) => (count === 1 ? "1 togs inte" : `${count} togs inte`),
};

/** The inbox's texts for a room's locale; Swedish unless the locale is English. */
export function suggestionLabelsFor(locale: string): SuggestionLabels {
  return locale.startsWith("en") ? suggestionsEn : suggestionsSv;
}

export { suggestionsEn, suggestionsSv };
