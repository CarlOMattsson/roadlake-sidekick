/**
 * Words of a Step's Actions list that no other list shares: the count under the Step title that opens the list,
 * the section name, the empty and forbidden texts and the Action row's menu hint. The shared words (Up, Down, Archive, Restore, Undo, the refusals)
 * stay in manage-labels.ts. Swedish comes first and is the default; the English key set must stay
 * identical to it (tests/features/work-app/steps/step-actions.test.tsx checks that).
 */
export const stepActionsLabelsSv = {
  /** The count under the Step's title; once the list is read it also says how many are done (done of total). */
  countMeta: (count: number, done = 0) =>
    done > 0
      ? count === 1
        ? `${done} av ${count} åtgärd klar`
        : `${done} av ${count} åtgärder klara`
      : `${count} ${count === 1 ? "åtgärd" : "åtgärder"}`,
  none: "Inga åtgärder.",
  forbidden: "Du har inte behörighet att se åtgärderna.",
  sectionFor: (title: string) => `Åtgärder för steget ${title}`,
  menuHint: "Håll inne en åtgärd för fler val.",
  menuKeys: "Högerklicka på en åtgärd eller tryck Shift+F10 för fler val.",
};
export type StepActionsLabels = typeof stepActionsLabelsSv;

export const stepActionsLabelsEn: StepActionsLabels = {
  countMeta: (count, done = 0) =>
    done > 0
      ? `${done} of ${count} ${count === 1 ? "action" : "actions"} done`
      : `${count} ${count === 1 ? "action" : "actions"}`,
  none: "No actions.",
  forbidden: "You don’t have access to these actions.",
  sectionFor: (title) => `Actions for step ${title}`,
  menuHint: "Touch and hold an action for more options.",
  menuKeys: "Right-click an action or press Shift+F10 for more options.",
};

/** The words for a work locale: Swedish for "sv-SE", English otherwise. */
export function stepActionsLabelsFor(dateLocale: string): StepActionsLabels {
  return dateLocale.toLowerCase().startsWith("sv")
    ? stepActionsLabelsSv
    : stepActionsLabelsEn;
}
