import type { AppLocale } from "./app-locale";

/**
 * Words of the license signal (license-state.ts, license-mark.tsx). Kept next to it, not in @/i18n, so the MCP App
 * bundle does not pull in the Sidekick app catalogue. The type makes the Swedish and English sets identical. Swedish is
 * the default. The words are "licens" and "Köp licens"; never "stöd", "donation" or "tips" (see docs/decisions/log.md D-083: license terms).
 */
export type LicenseLabels = {
  /** The coin's accessible name. The coin has no text of its own. */
  mark: string;
  /** The words beside the coin at the end of a full view: the state in two words, never a sentence. */
  footFree: string;
  footExpired: string;
  /** The row's first sentence, free version. */
  unlicensed: string;
  /** The row's first sentence after the license ran out; `date` is empty when the server named no day. */
  expired: (date: string) => string;
  /** The licensed row: "Licensierad till Alex Exempel · t.o.m. 9 nov 2027". Either part may be absent. */
  licensed: (licensee: string | undefined, date: string) => string;
  buy: string;
  /** Said in place of the buy button while LICENSE_BUY_URL is empty (no link to the shop yet). */
  buySoon: string;
  enterKey: string;
  /** The key field's label (visually hidden: the button above names it). */
  keyField: string;
  save: string;
  saving: string;
  cancel: string;
  /** Said once after a key was saved. */
  saved: string;
  /** The server answered `accepted: false`: said calmly, by the field. */
  invalidKey: string;
  /** The key is a real one, but its last day has passed. */
  expiredKey: (date: string) => string;
  /** No answer, or a refusal: the shared error notice says this. */
  saveFailed: string;
  /** The date locale of `workDate`. */
  dateLocale: string;
};

export const licenseLabelsSv: LicenseLabels = {
  mark: "Gratisversion – visa licens",
  footFree: "Gratisversion",
  footExpired: "Licensen har gått ut",
  unlicensed: "Gratisversion. Du får gärna köpa en licens.",
  expired: (date) =>
    date
      ? `Licensen gick ut ${date}. Du får gärna köpa en ny.`
      : "Licensen har gått ut. Du får gärna köpa en ny.",
  licensed: (licensee, date) =>
    [
      licensee ? `Licensierad till ${licensee}` : "Licensierad",
      date && `t.o.m. ${date}`,
    ]
      .filter(Boolean)
      .join(" · "),
  buy: "Köp licens",
  buySoon: "Licensnycklar säljs snart.",
  enterKey: "Ange licensnyckel",
  keyField: "Licensnyckel",
  save: "Spara",
  saving: "Sparar …",
  cancel: "Avbryt",
  saved: "Licensen är sparad.",
  invalidKey: "Nyckeln kunde inte godkännas.",
  expiredKey: (date) =>
    date ? `Nyckeln gick ut ${date}.` : "Nyckeln har gått ut.",
  saveFailed: "Nyckeln kunde inte sparas.",
  dateLocale: "sv-SE",
};

export const licenseLabelsEn: LicenseLabels = {
  mark: "Free version. Show license",
  footFree: "Free version",
  footExpired: "License expired",
  unlicensed: "Free version. You’re welcome to buy a license.",
  expired: (date) =>
    date
      ? `Your license expired on ${date}. You’re welcome to buy a new one.`
      : "Your license has expired. You’re welcome to buy a new one.",
  licensed: (licensee, date) =>
    [licensee ? `Licensed to ${licensee}` : "Licensed", date && `until ${date}`]
      .filter(Boolean)
      .join(" · "),
  buy: "Buy a license",
  buySoon: "License keys will be on sale soon.",
  enterKey: "Enter license key",
  keyField: "License key",
  save: "Save",
  saving: "Saving…",
  cancel: "Cancel",
  saved: "License saved.",
  invalidKey: "That key wasn’t accepted.",
  expiredKey: (date) =>
    date ? `That key expired on ${date}.` : "That key has expired.",
  saveFailed: "Couldn’t save the key.",
  dateLocale: "en-GB",
};

export function licenseLabelsFor(locale: AppLocale): LicenseLabels {
  return locale === "en" ? licenseLabelsEn : licenseLabelsSv;
}
