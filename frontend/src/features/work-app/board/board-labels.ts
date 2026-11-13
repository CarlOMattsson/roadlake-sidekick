/**
 * Words of Status (the board) that no other view shares. Swedish comes first and is the default; the English key set
 * must stay identical to it. The word set for one locale is picked with boardLabelsFor(t.dateLocale).
 */
export const boardLabelsSv = {
  /** The board's next page, after every status: it reads more Tasks of all of them. */
  showMore: "Visa fler uppgifter",
};
export type BoardLabels = typeof boardLabelsSv;

export const boardLabelsEn: BoardLabels = {
  showMore: "Show more tasks",
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function boardLabelsFor(dateLocale: string): BoardLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? boardLabelsSv
    : boardLabelsEn;
}
