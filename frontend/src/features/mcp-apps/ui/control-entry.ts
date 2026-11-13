import type { AppLocale } from "../app-locale";
import type { RoomTarget } from "../room-types";

/**
 * The last entry of every room's ⋯ menu: "Minne och kontroll" (en "Memory and control"), the same words as the Control
 * room's own heading, so whoever wonders what Sidekick remembers finds it from any room. It opens the Control room on its
 * memory view, the answer to that question; a deletion's receipt names the way to the trash itself
 * ("Minne och kontroll › Borttaget"). The room asks for the target; the shell decides how it is shown.
 */
export function controlEntry(locale: AppLocale): {
  label: string;
  target: RoomTarget;
} {
  return {
    label: locale === "en" ? "Memory and control" : "Minne och kontroll",
    target: { room: "control", view: "memory" },
  };
}
