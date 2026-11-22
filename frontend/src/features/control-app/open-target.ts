import type { RoomTarget } from "../mcp-apps/room-types";

/** A record by its kind and id: a trash row, a change, or the record an activity entry names. */
export type OpenableRecord = {
  kind: string;
  id: string;
  label?: string | null | undefined;
};

/**
 * Where a record can be opened. Only the kinds a room has a page for are listed; a step, an action or a shopping item
 * has none, so its receipt or its history row offers no link.
 */
export function openTargetOf(item: OpenableRecord): RoomTarget | undefined {
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
