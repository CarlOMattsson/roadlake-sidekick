/**
 * Texts of the Start room's home view (sv and en with equal keys): its headings, its rows, the ready conversations'
 * answers and receipts. Every sentence is put together from get_start's counts and closed codes; the only text the
 * server writes is the insight line and the titles, and those are shown as data, never as words of this file.
 */
type Part =
  | "insight"
  | "ready"
  | "suggestions"
  | "today"
  | "waiting"
  | "since_last"
  | "more";

const homeEn = {
  dateLocale: "en-GB",
  /** The room's name in the strip ("Home" in English, "Start" in Swedish). */
  title: "Home",
  moreActions: "More actions for Home",
  refresh: "Refresh",
  /** Under an insight a model wrote (the latest automation run's own summary). */
  aiWritten: "Written by AI in an automation",
  readyHeading: "Ready to talk",
  readySince: (time: string) => `Ready since ${time}`,
  start: "Start",
  skip: "Skip today",
  /** What the card says where it cannot send the phrase itself (the phone app has no chat). */
  sayInClaude: "Ask Claude in the Claude app:",
  /** The phrase shown as text; the one sent also names the conversation's id. */
  startPhrase: (title: string) => `Start the ready conversation “${title}”`,
  startMessage: (title: string, id: string) =>
    `Start the ready conversation “${title}” (${id}).`,
  sent: "Sent to Claude",
  skipped: (title: string) => `Skipped today: ${title}`,
  unskipped: (title: string) => `Back for today: ${title}`,
  undo: "Undo",
  skipFailed: "Could not skip it. Try again.",
  suggestions: "Suggestions",
  suggestionsWaiting: (pending: number) =>
    pending === 1
      ? "1 waits for your answer"
      : `${pending} wait for your answer`,
  /** The ring of a task of today: its accessible name, the receipt after it, Ångra's receipt and the failures. */
  completeTask: (title: string) => `Mark ${title} as done`,
  taskDone: (title: string) => `Done: ${title}`,
  taskReopened: (title: string) => `Reopened: ${title}`,
  completeFailed: "Could not mark it as done. Try again.",
  reopenFailed: "Could not undo. Try again.",
  todayTitle: "Today",
  todayHeading: (count: number) => `Today (${count})`,
  openAgenda: "Open Agenda",
  more: (count: number) => `${count} more`,
  dueToday: "Today",
  waitingTitle: "Waiting on others",
  waitingHeading: (count: number) => `Waiting on others (${count})`,
  /** "Erik Sjöstrand · since 13 Nov"; without a name only the date. */
  waitingSince: (date: string) => `since ${date}`,
  waitingMore: (count: number, capped: boolean) =>
    capped
      ? `${count}+ more wait`
      : count === 1
        ? "1 more waits"
        : `${count} more wait`,
  automations: "Automations",
  failedToday: (count: number) =>
    count === 1 ? "1 failed today" : `${count} failed today`,
  /** "Since you last looked: 3 runs · 1 failed · 5 new suggestions · 2 answered". */
  sinceLast: "Since you last looked",
  runs: (count: number) => (count === 1 ? "1 run" : `${count} runs`),
  failedRuns: (count: number) => `${count} failed`,
  created: (count: number) =>
    count === 1 ? "1 new suggestion" : `${count} new suggestions`,
  decided: (count: number) => `${count} answered`,
  empty: "Nothing is waiting for you right now.",
  /** A part the server could not read; the rest of the page stands. */
  unavailable: {
    insight: "Couldn’t refresh the insight",
    ready: "Couldn’t refresh the ready conversations",
    suggestions: "Couldn’t refresh the suggestions",
    today: "Couldn’t refresh today’s tasks",
    waiting: "Couldn’t refresh what waits on others",
    since_last: "Couldn’t refresh the automations",
    more: "Couldn’t refresh the counts",
  } satisfies Record<Part, string>,
};

export type HomeLabels = typeof homeEn;

const homeSv: HomeLabels = {
  dateLocale: "sv-SE",
  title: "Start",
  moreActions: "Fler val för Start",
  refresh: "Uppdatera",
  aiWritten: "Skrivet av AI i en automation",
  readyHeading: "Redo att prata",
  readySince: (time) => `Redo sedan ${time}`,
  start: "Starta",
  skip: "Hoppa över idag",
  sayInClaude: "Be Claude i Claude-appen:",
  startPhrase: (title) => `Starta det färdiga samtalet ”${title}”`,
  startMessage: (title, id) =>
    `Starta det färdiga samtalet ”${title}” (${id}).`,
  sent: "Skickat till Claude",
  skipped: (title) => `Hoppas över idag: ${title}`,
  unskipped: (title) => `Tillbaka för idag: ${title}`,
  undo: "Ångra",
  skipFailed: "Det gick inte att hoppa över. Försök igen.",
  suggestions: "Förslag",
  suggestionsWaiting: (pending) => `${pending} väntar på ditt svar`,
  completeTask: (title) => `Markera ${title} som klar`,
  taskDone: (title) => `Klar: ${title}`,
  taskReopened: (title) => `Öppen igen: ${title}`,
  completeFailed: "Det gick inte att markera som klar. Försök igen.",
  reopenFailed: "Det gick inte att ångra. Försök igen.",
  todayTitle: "Idag",
  todayHeading: (count) => `Idag (${count})`,
  openAgenda: "Öppna Agenda",
  more: (count) => `${count} till`,
  dueToday: "Idag",
  waitingTitle: "Väntar på andra",
  waitingHeading: (count) => `Väntar på andra (${count})`,
  waitingSince: (date) => `sedan ${date}`,
  waitingMore: (count, capped) =>
    capped ? `${count}+ till väntar` : `${count} till väntar`,
  automations: "Automationer",
  failedToday: (count) => `${count} misslyckades idag`,
  sinceLast: "Sedan sist",
  runs: (count) => (count === 1 ? "1 körning" : `${count} körningar`),
  failedRuns: (count) => `${count} misslyckades`,
  created: (count) => (count === 1 ? "1 nytt förslag" : `${count} nya förslag`),
  decided: (count) => `${count} besvarade`,
  empty: "Inget som väntar på dig just nu.",
  unavailable: {
    insight: "Kunde inte uppdatera insikten",
    ready: "Kunde inte uppdatera de färdiga samtalen",
    suggestions: "Kunde inte uppdatera förslagen",
    today: "Kunde inte uppdatera dagens uppgifter",
    waiting: "Kunde inte uppdatera det som väntar på andra",
    since_last: "Kunde inte uppdatera automationerna",
    more: "Kunde inte uppdatera siffrorna",
  },
};

export function homeLabelsFor(locale: string): HomeLabels {
  return locale.startsWith("en") ? homeEn : homeSv;
}

/** Both languages, for the locale parity test. */
export const HOME_LABELS = { sv: homeSv, en: homeEn } as const;
