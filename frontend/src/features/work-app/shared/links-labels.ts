/**
 * Words of the link controls: removing an external pointer from a Task (the Underlag section). The shared words (Remove link,
 * Undo, Read again, Try again and the four refusals) stay in manage-labels.ts; the word set for one
 * locale is picked with linksLabelsFor(t.dateLocale). The Swedish and English key sets must stay
 * identical (task-references.test.tsx checks that).
 */
export const linksLabelsSv = {
  references: "Underlag",
  /** The kind of an external pointer, by the server's kind value. */
  kind: {
    mail: "Mejl",
    calendar_event: "Kalenderhändelse",
    document: "Dokument",
  },
  /** Under the list: only the pointer goes; the source keeps its item. */
  keptNote:
    "Bara kopplingen tas bort. Mejlet, händelsen eller dokumentet finns kvar hos leverantören.",
  more: "Visa fler",
  loading: "Läser…",
  readMoreFailed: "Det gick inte att läsa nästa del av listan.",
  removeReferenceFor: (title: string) => `Ta bort koppling till ${title}`,
  referenceUnlinked: (title: string) => `Tog bort kopplingen till ”${title}”.`,
  /** The meta line of a Contact or Project row whose link was removed from the ⋯, before its Ångra. */
  linkRemoved: "Kopplingen borttagen",
  /** The long-press tip and the screen-reader hint of a linked row (a Contact under a Task, a Project under a Contact). */
  rowMenuHint: "Håll inne en rad för fler val.",
  rowMenuKeys: "Högerklicka på en rad eller tryck Shift+F10 för fler val.",
};
export type LinksLabels = typeof linksLabelsSv;

export const linksLabelsEn: LinksLabels = {
  references: "References",
  kind: {
    mail: "Email",
    calendar_event: "Calendar event",
    document: "Document",
  },
  keptNote:
    "Only the link is removed. The email, event, or document stays with its provider.",
  more: "Show more",
  loading: "Loading…",
  readMoreFailed: "Couldn’t load more of the list.",
  removeReferenceFor: (title) => `Remove link to ${title}`,
  referenceUnlinked: (title) => `Removed the link to “${title}”.`,
  linkRemoved: "Link removed",
  rowMenuHint: "Touch and hold a row for more options.",
  rowMenuKeys: "Right-click a row or press Shift+F10 for more options.",
};

/** The link words for a work locale: Swedish for "sv-SE", English otherwise. */
export function linksLabelsFor(dateLocale: string): LinksLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? linksLabelsSv
    : linksLabelsEn;
}
