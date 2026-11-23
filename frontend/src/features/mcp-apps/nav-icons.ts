/**
 * What the room strip's cells draw. `auto`, the default, follows the frame: the rooms' names alone where there is
 * room for them, and in a phone's frame what `label` draws there, each room's glyph with the name in the room that is
 * open, so the row holds five cells and the glyphs are learnt by moving between the rooms. The other three are the
 * instance's choice for every width: `off`, the names alone; `label`, each room's glyph before its name (in a phone's
 * frame the name in the open room only); `only`, the glyphs alone. A cell that does not draw its name is named for
 * assistive technology and in a tooltip. It is a Sidekick setting, SIDEKICK_MCP_APP_NAV_ICONS, which the backend
 * writes into the app document as `<meta name="sidekick-nav-icons">`; `auto` when the meta is missing or unknown. The
 * phone app has no such document: the owner chooses there (mobile/app-nav-icons.ts) and the shell is handed the choice.
 */
export const NAV_ICON_MODES = ["auto", "off", "label", "only"] as const;
export type NavIcons = (typeof NAV_ICON_MODES)[number];
/** What a strip draws once its frame is known: `auto` is one of the other three by then. */
export type StripFace = Exclude<NavIcons, "auto">;

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

/**
 * The face `mode` gives a strip. `phone` is a phone's frame at an ordinary text size (use-shell-measures.ts): there
 * `auto` draws the glyphs, with the name in the open room. Everywhere else, large text on a phone included, it is the
 * names alone: they are large enough there, and the chrome keeps its bound.
 */
export function stripFace(mode: NavIcons, phone: boolean): StripFace {
  if (mode !== "auto") return mode;
  return phone ? "label" : "off";
}
