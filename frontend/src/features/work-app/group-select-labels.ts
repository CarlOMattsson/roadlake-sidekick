/**
 * Words of the place picker (GroupSelect): where a Task belongs, a Project or a Process under a Domain, or nowhere.
 * The Swedish and English key sets must stay identical.
 */
export const groupSelectLabelsSv = {
  /** The picker's name, and the chip's word on the Task page. */
  place: "Plats",
  /** No Domain, Project or Process: the Task waits in To sort. */
  none: "Ingen plats (Att sortera)",
  /** A Domain alone, without a Project or Process. */
  domainOnly: (domain: string) => `${domain}, utan projekt`,
  /** A Process among the options: the word says it is not a Project. */
  processOption: (title: string) => `${title} (process)`,
  loading: "Hämtar platser…",
  failed: "Kunde inte hämta platserna.",
  /** The language the shared error notice speaks for its retry button (ErrorNotice). */
  locale: "sv",
};

export type GroupSelectLabels = typeof groupSelectLabelsSv;

export const groupSelectLabelsEn: GroupSelectLabels = {
  place: "Place",
  none: "No place (Unsorted)",
  domainOnly: (domain) => `${domain}, no project`,
  processOption: (title) => `${title} (process)`,
  loading: "Loading places…",
  failed: "Couldn’t load the places.",
  locale: "en",
};

/** The picker's words for a work locale: Swedish for "sv-SE", English otherwise. */
export function groupSelectLabelsFor(dateLocale: string): GroupSelectLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? groupSelectLabelsSv
    : groupSelectLabelsEn;
}
