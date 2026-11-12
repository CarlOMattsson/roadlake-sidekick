/**
 * The phone's choice of app language. The Claude apps take their language from the server's
 * `<meta name="sidekick-app-locale">`; the phone's bundle carries the same meta (Swedish unless built otherwise), and
 * the owner may choose Svenska or English on the pairing screen or in Inställningar. The choice is kept in the page's
 * own storage, so it outlives a restart and goes with the app's data, and it is written into the meta, so every room
 * that reads `appLocale()` follows it. The widget hears it through `setLocale` (mobile-app.tsx). The phone's own
 * language is never used.
 */
import {
  appLocale,
  applyAppLocale,
  type AppLocale,
} from "@/features/mcp-apps/app-locale";

export const APP_LANGUAGE_KEY = "sidekick.appLocale";

function stored(): AppLocale | undefined {
  try {
    const value = localStorage.getItem(APP_LANGUAGE_KEY);
    return value === "sv" || value === "en" ? value : undefined;
  } catch {
    return undefined;
  }
}

/** Writes `locale` where the rooms read it: the document's meta, `lang` on the page and its root. */
function declare(locale: AppLocale, doc: Document) {
  let meta = doc.querySelector<HTMLMetaElement>(
    'meta[name="sidekick-app-locale"]',
  );
  if (!meta) {
    meta = doc.createElement("meta");
    meta.name = "sidekick-app-locale";
    doc.head.append(meta);
  }
  meta.content = locale;
  applyAppLocale(locale, doc);
}

/** The language the app starts in: the owner's choice when there is one, else the bundle's (Swedish by default). */
export function startAppLanguage(doc: Document = document): AppLocale {
  const locale = stored() ?? appLocale(doc);
  declare(locale, doc);
  return locale;
}

/** Keeps the owner's choice and declares it; the caller draws the app again in it. */
export function chooseAppLanguage(
  locale: AppLocale,
  doc: Document = document,
): void {
  try {
    localStorage.setItem(APP_LANGUAGE_KEY, locale);
  } catch {
    // Without storage the choice holds until the app is closed.
  }
  declare(locale, doc);
}
