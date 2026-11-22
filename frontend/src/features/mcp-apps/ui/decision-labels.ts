/**
 * Texts of the decision family (decision-card.tsx, approve-group.tsx, trust-note.tsx): sv and en with equal keys.
 * They follow the room's locale ("sv-SE", "en-GB", "sv", "en"), so every suggestion, ready conversation and suspicious
 * suggestion says the same words on the same buttons, whichever view draws it. What the suggestion is about (its
 * title, its changes, its "why") comes from the server in the app's language and is not here. What a check found is:
 * the server sends closed codes (decision-codes.ts) and these are their sentences, one short sentence each, so a trust
 * note never shows text a mail or a model wrote.
 */
import type { ApplyError, CheckReason, ScreeningFlag } from "./decision-codes";

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
  /** After the source in the kicker, when the owner changed the suggestion before deciding. */
  edited: "edited by you",
  /** An approval the server refused with a closed code; it replaces `failedApprove`. */
  applyErrors: {
    project_gone:
      "The project no longer exists. Edit the suggestion or dismiss it.",
    conflict:
      "Something changed since the suggestion came. Refresh and try again.",
    invalid_payload:
      "The suggestion cannot be used as it is. Edit it or dismiss it.",
    not_permitted: "This change is not allowed. Dismiss the suggestion.",
  } satisfies Record<ApplyError, string>,
  /** What the screen found, in the trust note. */
  flags: {
    contains_link: "The suggestion contains a link.",
    payment_related: "The suggestion is about a payment.",
    contact_detail_unverified:
      "The e-mail address is not on the sender's domain.",
    homoglyph_domain: "An address mixes letters from different alphabets.",
    instruction_like_text: "The text reads like an instruction to an AI.",
    duplicate_existing: "You already have something like it.",
    large_batch: "The source gave unusually many suggestions at once.",
  } satisfies Record<ScreeningFlag, string>,
  /** What the checker found, after the flags; a code that means the same as a flag has the same sentence. */
  checkReasons: {
    out_of_scope: "It is outside what the automation is for.",
    destructive_intent: "It looks meant to remove or overwrite something.",
    instruction_like_text: "The text reads like an instruction to an AI.",
    mismatch_with_source: "It does not match its source.",
    payment_related: "The suggestion is about a payment.",
    contact_detail_unverified:
      "The e-mail address is not on the sender's domain.",
    duplicate_likely: "You already have something like it.",
  } satisfies Record<Exclude<CheckReason, "other">, string>,
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
  edited: "ändrad av dig",
  applyErrors: {
    project_gone:
      "Projektet finns inte längre. Ändra förslaget eller avböj det.",
    conflict:
      "Något har ändrats sedan förslaget kom. Uppdatera och försök igen.",
    invalid_payload:
      "Förslaget går inte att använda som det är. Ändra det eller avböj det.",
    not_permitted: "Den här ändringen är inte tillåten. Avböj förslaget.",
  },
  flags: {
    contains_link: "Förslaget innehåller en länk.",
    payment_related: "Förslaget handlar om en betalning.",
    contact_detail_unverified:
      "E-postadressen hör inte till avsändarens domän.",
    homoglyph_domain: "En adress blandar bokstäver från olika alfabet.",
    instruction_like_text: "Texten låter som en instruktion till en AI.",
    duplicate_existing: "Du har redan något likadant.",
    large_batch: "Källan gav ovanligt många förslag på en gång.",
  },
  checkReasons: {
    out_of_scope: "Det ligger utanför vad automationen är till för.",
    destructive_intent: "Det ser ut att vilja ta bort eller skriva över något.",
    instruction_like_text: "Texten låter som en instruktion till en AI.",
    mismatch_with_source: "Det stämmer inte med källan.",
    payment_related: "Förslaget handlar om en betalning.",
    contact_detail_unverified:
      "E-postadressen hör inte till avsändarens domän.",
    duplicate_likely: "Du har redan något likadant.",
  },
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
