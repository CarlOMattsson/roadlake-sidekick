/**
 * What the entry's reading and writing views add (the owner's text first, the quiet writing line, the neighbouring
 * entries). Spread into journalEn and journalSv through label-parts.ts, so components read them as `t.<key>`. The Swedish
 * and English key sets must stay identical (journal-entry-read.test.tsx checks it). `entryReadFor` is kept only for
 * that test, which picks the language from the labels' `dateLocale`.
 */
export const entryReadEn = {
  /** The fold under the owner's text, named by what it holds first. */
  claudeSummary: "Claude's summary",
  /** The placeholders of the writing fields; the visible labels are hidden but stay the fields' names. */
  titlePlaceholder: "Title",
  textPlaceholder: "How was the day?",
  appendPlaceholder: "Keep writing…",
  /** The quiet line under the field: the day, then the number of words ("Friday 20 November · 214 words"). */
  writeMeta: (day: string | undefined, words: number): string =>
    `${day ? `${day} · ` : ""}${words} ${words === 1 ? "word" : "words"}`,
  /** The two ends of the entry view: the group's name and its buttons. */
  neighbours: "More entries",
  previousEntry: "Previous entry",
  nextEntry: "Next entry",
};

export type EntryReadLabels = typeof entryReadEn;

export const entryReadSv: EntryReadLabels = {
  claudeSummary: "Claudes sammanfattning",
  titlePlaceholder: "Rubrik",
  textPlaceholder: "Hur var dagen?",
  appendPlaceholder: "Fortsätt skriva…",
  writeMeta: (day: string | undefined, words: number): string =>
    `${day ? `${day} · ` : ""}${words} ord`,
  neighbours: "Fler anteckningar",
  previousEntry: "Föregående anteckning",
  nextEntry: "Nästa anteckning",
};

/** The labels of the language the journal labels carry (`dateLocale` "sv-SE" or "en-GB"). */
export function entryReadFor(labels: { dateLocale: string }): EntryReadLabels {
  return labels.dateLocale.startsWith("sv") ? entryReadSv : entryReadEn;
}
