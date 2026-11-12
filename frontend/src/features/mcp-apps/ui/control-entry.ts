import type { AppLocale } from "../app-locale";
import type { RoomTarget } from "../room-types";

/**
 * The last entry of every room's ⋯ menu: "Minne och kontroll" (en "Memory and control"), the same words as the Control
 * room's own heading (owner's decision 2026-11-11), so whoever wonders what Sidekick remembers finds it from any room. It
 * opens the Control room on its trash view (design §2, Kontrolls navigering). The room asks for the target; the shell
 * decides how it is shown.
 */
export function controlEntry(locale: AppLocale): {
  label: string;
  target: RoomTarget;
} {
  return {
    label: locale === "en" ? "Memory and control" : "Minne och kontroll",
    target: { room: "control", view: "trash" },
  };
}
