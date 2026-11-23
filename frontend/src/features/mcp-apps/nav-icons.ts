/**
 * What the room strip's cells draw. `auto`, the default, follows the frame: the rooms' names alone where there is
 * room for them, and in a phone's frame each room's glyph over its name, so a row of five holds where five names do
 * not. The other three are the same at every width: `off`, the names alone; `label`, each room's glyph with its
 * name (before it, or over it in a phone's frame); `only`, the glyphs alone, each cell named for assistive technology
 * and in a tooltip. It is a Sidekick setting, SIDEKICK_MCP_APP_NAV_ICONS, which the backend writes into the app
 * document as `<meta name="sidekick-nav-icons">`; `auto` when the meta is missing or unknown. The phone app has no
 * such document: the owner chooses there (mobile/app-nav-icons.ts) and the shell is handed the choice.
 */
export const NAV_ICON_MODES = ["auto", "off", "label", "only"] as const;
export type NavIcons = (typeof NAV_ICON_MODES)[number];

/** Narrows an untrusted string (a meta's content, a stored choice); undefined when it is not one of the modes. */
export function navIconsFrom(value: string | null | undefined) {
  return NAV_ICON_MODES.find((mode) => mode === value);
}

/** What the document declares; undefined when it declares nothing, or something unknown. */
export function declaredNavIcons(doc: Document = document) {
  return navIconsFrom(
    doc.querySelector<HTMLMetaElement>('meta[name="sidekick-nav-icons"]')
      ?.content,
  );
}

export function navIcons(doc: Document = document): NavIcons {
  return declaredNavIcons(doc) ?? "auto";
}
