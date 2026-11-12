/**
 * Language of the Sidekick MCP Apps (work, journal, shopping). It is a Sidekick setting,
 * SIDEKICK_MCP_APP_LOCALE, which the backend writes into the app document as
 * `<meta name="sidekick-app-locale">`. Swedish when the meta is missing or unknown. The host's
 * locale is never used (the app language is its own setting). Dates follow the same choice, because each
 * app's labels carry their own date locale (sv-SE or en-GB).
 */
export type AppLocale = "sv" | "en";

export function appLocale(doc: Document = document): AppLocale {
  const declared = doc.querySelector<HTMLMetaElement>(
    'meta[name="sidekick-app-locale"]',
  )?.content;
  return declared === "en" ? "en" : "sv";
}

/**
 * Sets `lang` on the document element and on the app root, so the page and assistive technology
 * read the view in the chosen language. Every Sidekick MCP App calls this from its entry.
 */
export function applyAppLocale(locale: AppLocale, doc: Document = document) {
  doc.documentElement.lang = locale;
  doc.getElementById("root")?.setAttribute("lang", locale);
}
