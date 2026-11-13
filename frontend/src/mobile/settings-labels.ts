import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { TestPushOutcome } from "./sidekick-native";

/**
 * The texts of the phone's settings (settings-panel.tsx). The types make the Swedish and English sets identical (locale
 * parity); Swedish is the default. Headings and buttons end without a full stop, sentences end with one (designsystem
 * §1.6). `dateLocale` is the Work app's date locale, so dates read as everywhere else ("fre 13 nov").
 */
export type SettingsLabels = {
  dateLocale: string;
  /** The entry at the end of the Work room's ⋯ menu, in Control's place, and the title of the settings. */
  title: string;
  notificationsHeading: string;
  /** The heading over Svenska | English. */
  languageHeading: string;
  /** By the state `pushStatus` reads. */
  push: {
    on: string;
    install: string;
    denied: string;
    registering: string;
    /** The button under each state that has a fix: ntfy missing, permission refused, permission still to be asked. */
    getNtfy: string;
    openSettings: string;
    allow: string;
    /** The server sends no notifications (`pushEnabled` false): nothing on the phone can turn them on. */
    serverOff: string;
  };
  pushFailed: string;
  loading: string;
  sendTest: string;
  sending: string;
  /** By the closed outcome of `sendTestPush`; `failed` when the call itself failed. */
  outcomes: Record<Exclude<TestPushOutcome, "rate_limited">, string> & {
    failed: string;
  };
  /** `rate_limited`, with the minutes until the next test when the server said them. */
  rateLimited: (minutes: number | undefined) => string;
  /** See docs/decisions/log.md D-079: what the lock screen shows follows the phone's own setting. */
  lockScreen: string;
  phoneHeading: string;
  /** The device label is empty. */
  unnamed: string;
  /** The host name of the server the phone is paired to. */
  server: (host: string) => string;
  pairedSince: (date: string) => string;
  renews: string;
  validUntil: (date: string) => string;
  notPaired: string;
  deviceFailed: string;
  unpair: string;
  unpairQuestion: string;
  unpairConfirm: string;
  unpairing: string;
  cancel: string;
  unpairFailed: string;
};

export const settingsLabelsSv: SettingsLabels = {
  dateLocale: "sv-SE",
  title: "Inställningar",
  notificationsHeading: "Aviseringar",
  languageHeading: "Språk",
  push: {
    on: "Aviseringar är på.",
    install:
      "Aviseringar levereras av den gratis appen ntfy. Installera den för att få dem.",
    denied:
      "Aviseringar är avstängda för Sidekick. Slå på dem i telefonens inställningar.",
    registering: "Aviseringar kopplas in…",
    getNtfy: "Hämta ntfy",
    openSettings: "Öppna aviseringsinställningar",
    allow: "Tillåt aviseringar",
    serverOff:
      "Servern skickar inga aviseringar. Den som sköter servern kan slå på dem.",
  },
  pushFailed: "Aviseringarnas läge kunde inte läsas.",
  loading: "Läser…",
  sendTest: "Skicka testavisering",
  sending: "Skickar…",
  outcomes: {
    queued: "Testavisering skickad.",
    no_subscription: "Aviseringar är inte kopplade än.",
    disabled: "Aviseringar är avstängda på servern.",
    offline: "Servern kunde inte nås. Försök igen när telefonen har nät.",
    unpaired: "Telefonen är inte kopplad längre.",
    failed: "Testaviseringen kunde inte skickas.",
  },
  rateLimited: (minutes) =>
    minutes === undefined
      ? "Högst 5 testaviseringar i timmen. Försök igen senare."
      : `Högst 5 testaviseringar i timmen. Försök igen om ${minutes}\u00a0min.`,
  lockScreen:
    "Låsskärmen visar titlar bara om telefonen tillåter känsligt innehåll där.",
  phoneHeading: "Den här telefonen",
  unnamed: "Telefon utan namn",
  server: (host) => `Server: ${host}`,
  pairedSince: (date) => `Kopplad sedan ${date}`,
  renews: "Inloggningen förnyas automatiskt.",
  validUntil: (date) => `Giltig till ${date}.`,
  notPaired: "Telefonen är inte kopplad.",
  deviceFailed: "Telefonens koppling kunde inte läsas.",
  unpair: "Koppla från den här telefonen",
  unpairQuestion:
    "Sidekick töms på telefonen. För att koppla igen behövs en ny kopplingskod.",
  unpairConfirm: "Koppla från",
  unpairing: "Kopplar från…",
  cancel: "Avbryt",
  unpairFailed: "Telefonen kunde inte kopplas från.",
};

export const settingsLabelsEn: SettingsLabels = {
  dateLocale: "en-GB",
  title: "Settings",
  notificationsHeading: "Notifications",
  languageHeading: "Language",
  push: {
    on: "Notifications are on.",
    install:
      "Notifications are delivered by the free ntfy app. Install it to get them.",
    denied:
      "Notifications are off for Sidekick. Turn them on in your phone’s settings.",
    registering: "Setting up notifications…",
    getNtfy: "Get ntfy",
    openSettings: "Open notification settings",
    allow: "Allow notifications",
    serverOff:
      "The server doesn’t send notifications. Whoever runs the server can turn them on.",
  },
  pushFailed: "Couldn’t check notification status.",
  loading: "Loading…",
  sendTest: "Send test notification",
  sending: "Sending…",
  outcomes: {
    queued: "Test notification sent.",
    no_subscription: "Notifications aren’t set up yet.",
    disabled: "Notifications are turned off on the server.",
    offline: "Couldn’t reach the server. Try again when your phone is online.",
    unpaired: "This phone is no longer connected.",
    failed: "Couldn’t send the test notification.",
  },
  rateLimited: (minutes) =>
    minutes === undefined
      ? "Up to 5 test notifications per hour. Try again later."
      : `Up to 5 test notifications per hour. Try again in ${minutes}\u00a0min.`,
  lockScreen:
    "The lock screen shows titles only if your phone allows sensitive content there.",
  phoneHeading: "This phone",
  unnamed: "Unnamed phone",
  server: (host) => `Server: ${host}`,
  pairedSince: (date) => `Connected since ${date}`,
  renews: "Sign-in renews automatically.",
  validUntil: (date) => `Valid until ${date}.`,
  notPaired: "This phone isn’t connected.",
  deviceFailed: "Couldn’t check this phone’s connection.",
  unpair: "Disconnect this phone",
  unpairQuestion:
    "Sidekick will be cleared from this phone. To connect again, you’ll need a new pairing code.",
  unpairConfirm: "Disconnect",
  unpairing: "Disconnecting…",
  cancel: "Cancel",
  unpairFailed: "Couldn’t disconnect this phone.",
};

export function settingsLabelsFor(locale: AppLocale): SettingsLabels {
  return locale === "en" ? settingsLabelsEn : settingsLabelsSv;
}
