/**
 * Texts of the decision family (decision-card.tsx, approve-group.tsx, trust-note.tsx): sv and en with equal keys.
 * They follow the room's locale ("sv-SE", "en-GB", "sv", "en"), so every suggestion, ready conversation and suspicious
 * suggestion says the same words on the same buttons, whichever view draws it. What the suggestion is about (its
 * title, its changes, its reason) comes from the server in the app's language and is not here.
 */
const decisionEn = {
  approve: "Approve",
  approveBusy: "Approving…",
  dismiss: "Dismiss",
  dismissBusy: "Dismissing…",
  /** The suspicious card's way to the detail view, where it can still be approved. */
  review: "Review",
  edit: "Edit",
  /** The suspicious detail view's approve, which asks first. */
  approveAnyway: "Approve anyway",
  confirmAnyway: "Approve a suspicious suggestion?",
  cancel: "Cancel",
  why: "Why",
  /** Read between the value before and the value after a change ("före → efter" on screen). */
  changedTo: "changes to",
  /** The source of the suggestion, after the kicker: "from Morning mail". */
  from: (name: string) => `from ${name}`,
  /** Changes not shown on an inline card. */
  moreChanges: (count: number) => `+${count}`,
  moreChangesLabel: (count: number) =>
    count === 1 ? "1 more change" : `${count} more changes`,
  failedApprove: "Could not approve. Try again.",
  failedDismiss: "Could not dismiss. Try again.",
  trust: {
    unsure: "The check was unsure",
    suspicious: "Suspicious suggestion",
    /** Only in the detail view: the check did not run. */
    off: "Not checked",
    /** Only in the detail view, with the checker's confidence when it gave one. */
    ok: (confidence?: number) =>
      confidence === undefined ? "Checked" : `Checked · ${confidence} % sure`,
  },
  group: {
    /** All of the group is in: "Approve all 3". */
    all: (count: number) => `Approve all ${count}`,
    /** Some are left out, or more wait beyond the batch: "Approve 2". */
    some: (count: number) => `Approve ${count}`,
    none: "Approve",
    /** Suggestions beyond the batch: they wait for the next confirmation. */
    beyond: (count: number, max: number) =>
      count === 1
        ? `1 more after these, at most ${max} at a time`
        : `${count} more after these, at most ${max} at a time`,
  },
};

export type DecisionLabels = typeof decisionEn;

const decisionSv: DecisionLabels = {
  approve: "Godkänn",
  approveBusy: "Godkänner…",
  dismiss: "Avböj",
  dismissBusy: "Avböjer…",
  review: "Granska",
  edit: "Ändra",
  approveAnyway: "Godkänn ändå",
  confirmAnyway: "Godkänna ett misstänkt förslag?",
  cancel: "Avbryt",
  why: "Varför",
  changedTo: "ändras till",
  from: (name) => `från ${name}`,
  moreChanges: (count) => `+${count}`,
  moreChangesLabel: (count) =>
    count === 1 ? "1 ändring till" : `${count} ändringar till`,
  failedApprove: "Det gick inte att godkänna. Försök igen.",
  failedDismiss: "Det gick inte att avböja. Försök igen.",
  trust: {
    unsure: "Kontrollen var osäker",
    suspicious: "Misstänkt förslag",
    off: "Inte kontrollerad",
    ok: (confidence) =>
      confidence === undefined
        ? "Kontrollerad"
        : `Kontrollerad · säker ${confidence} %`,
  },
  group: {
    all: (count) => `Godkänn alla ${count}`,
    some: (count) => `Godkänn ${count}`,
    none: "Godkänn",
    beyond: (count, max) =>
      count === 1
        ? `1 till efter de här, högst ${max} åt gången`
        : `${count} till efter de här, högst ${max} åt gången`,
  },
};

/** The family's texts for a room's locale; Swedish unless the locale is English. */
export function decisionLabelsFor(locale: string): DecisionLabels {
  return locale.startsWith("en") ? decisionEn : decisionSv;
}

export { decisionEn, decisionSv };
