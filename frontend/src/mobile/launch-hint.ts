/**
 * The deep-link hint a launch carries (a widget tap, a notification, later a link): `?view=today`,
 * `?view=task&id=<uuid>` or `?view=settings` (the widget's license coin: the settings, where the license row is). It is
 * a hint, never an instruction: only these three views exist, a task needs a well-formed
 * id, and anything else (an unknown view, a missing or malformed id, a repeated parameter) opens Today. Whether the
 * task is the owner's is decided by the server when the room reads it.
 */
import { ROOT_VIEW, type NavEntry } from "@/features/mcp-apps/nav-state";

export type LaunchHint =
  { view: "today" } | { view: "task"; id: string } | { view: "settings" };

const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TODAY: LaunchHint = { view: "today" };
const SETTINGS: LaunchHint = { view: "settings" };

/** The hint of a query string ("?view=task&id=..." or without the "?"). Never throws; unknown is Today. */
export function parseLaunchHint(search: string | null | undefined): LaunchHint {
  if (typeof search !== "string" || search.length > 512) return TODAY;
  const params = new URLSearchParams(search);
  const views = params.getAll("view");
  if (views.length !== 1) return TODAY;
  if (views[0] === "today") return TODAY;
  if (views[0] === "settings") return SETTINGS;
  if (views[0] !== "task") return TODAY;
  const ids = params.getAll("id");
  const id = ids.length === 1 ? ids[0] : undefined;
  if (id === undefined || !UUID.test(id)) return TODAY;
  return { view: "task", id: id.toLowerCase() };
}

/**
 * Where the shell starts for a hint. Today is the Agenda of the Work room; a task is its detail, with the Agenda
 * under it so Back leads there. The settings are not a shell entry: the room under them is Today, and the caller opens
 * the settings on top when `hint.view === "settings"`.
 */
export function startEntryOf(hint: LaunchHint): NavEntry {
  if (hint.view === "task") return { room: "work", view: "task", id: hint.id };
  return { room: "work", view: ROOT_VIEW };
}
