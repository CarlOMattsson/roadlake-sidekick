/**
 * The Journal's inline day card: its one link into the room ("Öppna Dagbok ›", then what the rows leave out).
 * Spread into journalEn and journalSv (label-parts.ts).
 */
export const glanceEn = {
  /** The card's open phrase; the link adds the › and, when entries are left out, `glanceMore`. */
  glanceOpen: "Open Journal",
  /** What the rows leave out, after the open phrase ("2 more"); "2+ more" when the day has another page to read. */
  glanceMore: (hidden: number, more: boolean): string =>
    `${hidden}${more ? "+" : ""} more`,
};

export const glanceSv: typeof glanceEn = {
  glanceOpen: "Öppna Dagbok",
  glanceMore: (hidden: number, more: boolean): string =>
    `${hidden}${more ? "+" : ""} till`,
};
