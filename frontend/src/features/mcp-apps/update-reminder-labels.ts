import type { AppLocale } from "./app-locale";

/**
 * Words of the update reminder (update-notice.ts). Kept next to it, not in @/i18n, so the MCP App bundle does not pull
 * in the Sidekick app catalogue. The type makes the Swedish and English sets identical. Swedish is the default.
 */
export type UpdateReminderLabels = {
  /** Added to the accessible name of a ⋯ button while the reminder stands: the more-actions name and the update note. */
  moreSuffix: string;
  /** The row's first line: the age in days and the commit. */
  age: (days: number, commit: string) => string;
  /** Before the command: `howTo`. */
  howTo: string;
  /** The one button; it quiets the reminder for this commit only. */
  dismiss: string;
  /** Said once after the button, in place of the row. */
  dismissed: string;
};

export const updateReminderLabelsSv: UpdateReminderLabels = {
  moreSuffix: "uppdatering finns att hämta",
  age: (days, commit) =>
    `Den här versionen är ${days} ${days === 1 ? "dag" : "dagar"} gammal (commit ${commit})`,
  howTo: "Uppdatera med",
  dismiss: "Påminn inte för den här versionen",
  dismissed: "Okej, ingen mer påminnelse för den här versionen.",
};

export const updateReminderLabelsEn: UpdateReminderLabels = {
  moreSuffix: "update available",
  age: (days, commit) =>
    `This version is ${days} ${days === 1 ? "day" : "days"} old (commit ${commit})`,
  howTo: "Update with",
  dismiss: "Don’t remind me about this version",
  dismissed: "OK, no more reminders for this version.",
};

export function updateReminderLabelsFor(
  locale: AppLocale,
): UpdateReminderLabels {
  return locale === "en" ? updateReminderLabelsEn : updateReminderLabelsSv;
}
