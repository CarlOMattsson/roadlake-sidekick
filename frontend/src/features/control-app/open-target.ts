import type { RoomTarget } from "../mcp-apps/room-types";
import type { TrashItem } from "./transport";

/**
 * Where a restored record can be opened. Only the kinds a room has a page for are listed; a step, an action or a
 * shopping item has none, so its receipt offers no link.
 */
export function openTargetOf(item: TrashItem): RoomTarget | undefined {
  const label = item.label ?? undefined;
  switch (item.kind) {
    case "task":
    case "project":
    case "process":
      return { room: "work", view: item.kind, id: item.id, label };
    case "contact":
      return { room: "contacts", view: "contact", id: item.id, label };
    case "journal_entry":
      return { room: "journal", view: "entry", id: item.id };
    default:
      return undefined;
  }
}
