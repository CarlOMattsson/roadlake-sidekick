/**
 * Words of a Step's Actions list that no other list shares: the disclosure button, the section name,
 * the empty and forbidden texts. The shared words (Up, Down, Archive, Restore, Undo, the refusals)
 * stay in manage-labels.ts. Swedish comes first and is the default; the English key set must stay
 * identical to it (tests/step-actions.test.tsx checks that).
 */
export const stepActionsLabelsSv = {
  show: "Visa åtgärder",
  hide: "Dölj åtgärder",
  countHeading: (count: number) => `Åtgärder (${count})`,
  none: "Inga åtgärder.",
  forbidden: "Du har inte behörighet att se åtgärderna.",
  sectionFor: (title: string) => `Åtgärder för steget ${title}`,
};
export type StepActionsLabels = typeof stepActionsLabelsSv;

export const stepActionsLabelsEn: StepActionsLabels = {
  show: "Show actions",
  hide: "Hide actions",
  countHeading: (count) => `Actions (${count})`,
  none: "No actions.",
  forbidden: "You don’t have access to these actions.",
  sectionFor: (title) => `Actions for step ${title}`,
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function stepActionsLabelsFor(dateLocale: string): StepActionsLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? stepActionsLabelsSv
    : stepActionsLabelsEn;
}
