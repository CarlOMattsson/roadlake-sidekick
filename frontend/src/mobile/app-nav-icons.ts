/**
 * The phone's choice of what the room strip draws. In Claude it is the server's setting, written into the app document
 * (nav-icons.ts). The phone has no document from the server, so the owner chooses in Inställningar, under the language.
 * The choice is kept in the page's own storage, as the language is (app-language.ts), so it outlives a restart and goes
 * with the app's data; the shell is handed it.
 *
 * The default is `auto`, as in Claude, so the phone app follows the same model (issue #46, the owner's decision of
 * 2026-11-23): in a phone's frame at an ordinary text size each room's glyph, with the name in the open room only; at
 * large text, or on a tablet's wider frame, the names alone. The other three are the modes that are the same at every
 * width: the names alone, a glyph with each name, or the glyphs alone. A bundle that declares a mode starts in it.
 */
import { useState } from "react";

import {
  declaredNavIcons,
  navIconsFrom,
  type NavIcons,
} from "@/features/mcp-apps/nav-icons";

export const APP_NAV_ICON_CHOICES = [
  "auto",
  "off",
  "label",
  "only",
] as const satisfies readonly NavIcons[];
export type AppNavIcons = (typeof APP_NAV_ICON_CHOICES)[number];

export const APP_NAV_ICONS_KEY = "sidekick.navIcons";

function choiceFrom(mode: NavIcons | undefined): AppNavIcons | undefined {
  return APP_NAV_ICON_CHOICES.find((choice) => choice === mode);
}

function stored(): AppNavIcons | undefined {
  try {
    return choiceFrom(navIconsFrom(localStorage.getItem(APP_NAV_ICONS_KEY)));
  } catch {
    return undefined;
  }
}

/** The choice the app starts with, and how to change it: kept first, then drawn. */
export function useAppNavIcons(): [AppNavIcons, (next: AppNavIcons) => void] {
  const [icons, setIcons] = useState(
    () => stored() ?? choiceFrom(declaredNavIcons()) ?? "auto",
  );
  const choose = (next: AppNavIcons) => {
    try {
      localStorage.setItem(APP_NAV_ICONS_KEY, next);
    } catch {
      // Without storage the choice holds until the app is closed.
    }
    setIcons(next);
  };
  return [icons, choose];
}
