/**
 * Words of the refresh control on the inline board and agenda cards. Swedish is the default; the English key set
 * must stay identical to it. The set for one locale is picked with refreshLabelsFor(dateLocale), as the board's words are.
 */
export const refreshLabelsSv = {
  /** The button's name and tooltip. */
  refresh: "Uppdatera",
  /** Read aloud while the read runs. */
  refreshing: "Uppdaterar…",
  /** The line under the card's head when the read failed; the card keeps what it showed. */
  failed: "Det gick inte att uppdatera.",
  /** Replaces the date in the card's head after a refresh: "Uppdaterad 14:05". */
  updated: (time: string) => `Uppdaterad ${time}`,
};

export const refreshLabelsEn: typeof refreshLabelsSv = {
  refresh: "Refresh",
  refreshing: "Refreshing…",
  failed: "Couldn’t refresh.",
  updated: (time) => `Updated ${time}`,
};

export type RefreshLabels = typeof refreshLabelsSv;

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function refreshLabelsFor(dateLocale: string): RefreshLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? refreshLabelsSv
    : refreshLabelsEn;
}
