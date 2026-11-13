import type { AppLocale } from "@/features/mcp-apps/app-locale";

/**
 * The texts of the pairing screen. The types make the Swedish and English sets identical (locale parity); Swedish is
 * the default (the app language is its own setting). Headings and buttons end without a full
 * stop, sentences end with one (designsystem §1.6).
 */
export type PairingLabels = {
  title: string;
  /** The name of the language switch at the top of the screen, for assistive technology. */
  language: string;
  intro: string;
  serverLabel: string;
  serverPlaceholder: string;
  secretLabel: string;
  secretHint: string;
  /** The collapsible help on where the code comes from. */
  helpTitle: string;
  helpBody: string;
  helpLink: string;
  /** The button that shows the masked code, and the one that masks it again. */
  showSecret: string;
  hideSecret: string;
  submit: string;
  submitting: string;
  loading: string;
  /** The status could not be read from the phone. */
  statusFailed: string;
  retry: string;
  /** By field: what is wrong with it, shown by the field itself. */
  fieldErrors: {
    serverRequired: string;
    serverInvalid: string;
    codeRequired: string;
    codeShort: string;
    codeInvalid: string;
  };
  /** The question asked before a pairing link pairs the phone. `{host}` is the server the link names. */
  confirmTitle: string;
  confirmBody: string;
  confirm: string;
  cancel: string;
  /** Shown after the server refused the stored credential. */
  lost: string;
  /** Shown after the owner disconnected the phone in the settings, and the server confirmed. */
  unpaired: string;
  /** Shown after the owner disconnected the phone, when the server could not confirm (the phone is cleared anyway). */
  unpairedUnconfirmed: string;
  /**
   * Shown in the app when a pairing link reached a phone that is already paired and was dropped. `{host}` is the
   * server the phone is paired to; `linkIgnoredNoHost` is for a status that did not name it.
   */
  linkIgnored: string;
  linkIgnoredNoHost: string;
  /** The button that dismisses that line. */
  dismiss: string;
  /** By the closed error code of SidekickNative.pair; `fallback` for any other. */
  errors: Record<
    | "invalid_server_url"
    | "invalid_pairing_secret"
    | "pairing_invalid"
    | "rate_limited"
    | "network"
    | "timeout"
    | "secure_storage"
    | "previous_data_not_removed"
    | "already_paired"
    | "fallback",
    string
  >;
};

export const pairingLabelsSv: PairingLabels = {
  title: "Koppla till din Sidekick",
  language: "Språk",
  intro: "Skriv serverns adress och kopplingskoden från din server.",
  serverLabel: "Serveradress",
  serverPlaceholder: "https://din-server.example",
  secretLabel: "Kopplingskod",
  secretHint: "Koden gäller en gång och en kort stund.",
  helpTitle: "Var hittar jag koden?",
  helpBody:
    "Koden skapas på din Sidekick-server. Be den som driver servern om en kopplingslänk, eller om adressen och en kopplingskod.",
  helpLink:
    "Det enklaste är att öppna kopplingslänken på den här telefonen: då fylls adress och kod i åt dig, och du bekräftar innan telefonen kopplas.",
  showSecret: "Visa koden",
  hideSecret: "Dölj koden",
  submit: "Koppla",
  submitting: "Kopplar…",
  loading: "Läser kopplingen…",
  statusFailed: "Kopplingen kunde inte läsas.",
  retry: "Försök igen",
  fieldErrors: {
    serverRequired: "Skriv serverns adress.",
    serverInvalid:
      "Adressen ser inte rätt ut. Skriv den som https://din-server.example, utan något efter servernamnet.",
    codeRequired: "Skriv kopplingskoden.",
    codeShort: "Koden är för kort. Kontrollera att du fick med hela koden.",
    codeInvalid:
      "Koden innehåller tecken som inte hör hemma i en kod. Kontrollera och försök igen.",
  },
  confirmTitle: "Koppla till {host}?",
  confirmBody:
    "En länk vill koppla den här telefonen till servern {host}. Koppla bara om du själv skapade koden.",
  confirm: "Koppla",
  cancel: "Avbryt",
  lost: "Kopplingen har upphört. Koppla igen.",
  unpaired: "Telefonen är frånkopplad.",
  unpairedUnconfirmed:
    "Telefonen är frånkopplad, men servern kunde inte bekräfta det. Be den som sköter servern spärra telefonen, eller koppla den på nytt.",
  linkIgnored:
    "Telefonen är redan kopplad till {host}. Koppla från i Inställningar för att byta.",
  linkIgnoredNoHost:
    "Telefonen är redan kopplad. Koppla från i Inställningar för att byta.",
  dismiss: "Stäng",
  errors: {
    invalid_server_url:
      "Adressen måste börja med https:// och bara innehålla servern.",
    invalid_pairing_secret:
      "Koden ser inte rätt ut. Kontrollera och försök igen.",
    pairing_invalid:
      "Koden gäller inte längre eller är redan använd. Skapa en ny.",
    rate_limited: "För många försök. Vänta en minut och försök igen.",
    network: "Servern kunde inte nås. Kontrollera adressen och anslutningen.",
    timeout: "Servern svarade inte. Försök igen.",
    secure_storage: "Kopplingen kunde inte sparas säkert på telefonen.",
    previous_data_not_removed:
      "Den förra kopplingens data kunde inte raderas från telefonen. Starta om appen och försök igen. Om koden har gått ut, skapa en ny.",
    already_paired:
      "Telefonen är redan kopplad. Koppla från först om du vill koppla om.",
    fallback: "Kopplingen misslyckades. Försök igen.",
  },
};

export const pairingLabelsEn: PairingLabels = {
  title: "Connect to your Sidekick",
  language: "Language",
  intro: "Enter your server’s address and the pairing code from your server.",
  serverLabel: "Server address",
  serverPlaceholder: "https://your-server.example",
  secretLabel: "Pairing code",
  secretHint: "The code works once and only for a short time.",
  helpTitle: "Where do I find the code?",
  helpBody:
    "The code is created on your Sidekick server. Ask whoever runs the server for a pairing link, or for the address and a pairing code.",
  helpLink:
    "The easiest way is to open the pairing link on this phone: it fills in the address and the code for you, and you confirm before the phone is connected.",
  showSecret: "Show code",
  hideSecret: "Hide code",
  submit: "Connect",
  submitting: "Connecting…",
  loading: "Checking connection…",
  statusFailed: "Couldn’t check the connection.",
  retry: "Try again",
  fieldErrors: {
    serverRequired: "Enter the server’s address.",
    serverInvalid:
      "That address doesn’t look right. Write it as https://your-server.example, with nothing after the server name.",
    codeRequired: "Enter the pairing code.",
    codeShort: "The code is too short. Check that you copied all of it.",
    codeInvalid:
      "The code has characters that don’t belong in a code. Check it and try again.",
  },
  confirmTitle: "Connect to {host}?",
  confirmBody:
    "A link wants to connect this phone to the server {host}. Only connect if you created the code yourself.",
  confirm: "Connect",
  cancel: "Cancel",
  lost: "The connection has ended. Connect again.",
  unpaired: "This phone is disconnected.",
  unpairedUnconfirmed:
    "This phone is disconnected, but the server couldn’t confirm it. Ask whoever runs the server to revoke the phone, or connect it again.",
  linkIgnored:
    "This phone is already connected to {host}. Disconnect in Settings to switch.",
  linkIgnoredNoHost:
    "This phone is already connected. Disconnect in Settings to switch.",
  dismiss: "Dismiss",
  errors: {
    invalid_server_url:
      "The address must start with https:// and include only the server, with nothing after it.",
    invalid_pairing_secret:
      "That code doesn’t look right. Check it and try again.",
    pairing_invalid:
      "That code has expired or was already used. Create a new one.",
    rate_limited: "Too many attempts. Wait a minute and try again.",
    network:
      "Couldn’t reach the server. Check the address and your connection.",
    timeout: "The server didn’t respond. Try again.",
    secure_storage: "Couldn’t store the connection securely on this phone.",
    previous_data_not_removed:
      "The previous connection’s data couldn’t be removed from this phone. Restart the app and try again. If the code has expired, create a new one.",
    already_paired:
      "This phone is already connected. Disconnect first to connect again.",
    fallback: "Couldn’t connect. Try again.",
  },
};

export function pairingLabelsFor(locale: AppLocale): PairingLabels {
  return locale === "en" ? pairingLabelsEn : pairingLabelsSv;
}

/** The message for a closed code from SidekickNative.pair. */
export function pairingErrorMessage(
  labels: PairingLabels,
  code: string,
): string {
  return code in labels.errors && code !== "fallback"
    ? labels.errors[code as keyof PairingLabels["errors"]]
    : labels.errors.fallback;
}
