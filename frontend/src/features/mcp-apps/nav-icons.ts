/**
 * What the room strip's cells draw: `off`, the rooms' names alone (the default); `label`, each room's glyph before its
 * name; `only`, the glyphs alone, each cell named for assistive technology and in a tooltip. It is a Sidekick setting,
 * SIDEKICK_MCP_APP_NAV_ICONS, which the backend writes into the app document as `<meta name="sidekick-nav-icons">`.
 * Names alone when the meta is missing or unknown. The phone has no such document: the owner chooses there
 * (mobile/app-nav-icons.ts) and the shell is handed the choice.
 */
export const NAV_ICON_MODES = ["off", "label", "only"] as const;
export type NavIcons = (typeof NAV_ICON_MODES)[number];

/** Narrows an untrusted string (a meta's content, a stored choice); undefined when it is not one of the three. */
export function navIconsFrom(value: string | null | undefined) {
  return NAV_ICON_MODES.find((mode) => mode === value);
}

export function navIcons(doc: Document = document): NavIcons {
  const declared = doc.querySelector<HTMLMetaElement>(
    'meta[name="sidekick-nav-icons"]',
  )?.content;
  return navIconsFrom(declared) ?? "off";
}
