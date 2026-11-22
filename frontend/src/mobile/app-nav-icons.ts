/**
 * The phone's choice of what the room strip draws: the rooms' names, a glyph before each name, or the glyphs alone. In
 * Claude it is the server's setting, written into the app document (nav-icons.ts). The phone has no document from the
 * server, so the owner chooses in Inställningar, under the language. The choice is kept in the page's own storage, as
 * the language is (app-language.ts), so it outlives a restart and goes with the app's data; the shell is handed it.
 * Names alone until the owner chooses, unless the bundle declares otherwise.
 */
import { useState } from "react";

import {
  navIcons,
  navIconsFrom,
  type NavIcons,
} from "@/features/mcp-apps/nav-icons";

export const APP_NAV_ICONS_KEY = "sidekick.navIcons";

function stored(): NavIcons | undefined {
  try {
    return navIconsFrom(localStorage.getItem(APP_NAV_ICONS_KEY));
  } catch {
    return undefined;
  }
}

/** The choice the app starts with, and how to change it: kept first, then drawn. */
export function useAppNavIcons(): [NavIcons, (next: NavIcons) => void] {
  const [icons, setIcons] = useState(() => stored() ?? navIcons());
  const choose = (next: NavIcons) => {
    try {
      localStorage.setItem(APP_NAV_ICONS_KEY, next);
    } catch {
      // Without storage the choice holds until the app is closed.
    }
    setIcons(next);
  };
  return [icons, choose];
}
