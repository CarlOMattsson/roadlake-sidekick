import type { RoomTransport } from "../mcp-apps/room-types";
import type { EmptyResult, TrashList, TrashTransport } from "./transport";

/** The tool only the phone answers: it removes one trashed Task for good. */
export const ERASE_TOOL = "erase_trashed_task";

/**
 * The trash reads and writes, each one a tool called through the room's transport. Permanent removal is added only
 * where the host says it has the tool, `true` and nothing less: a host without `supportsTool` (Claude) never gets it.
 * The `confirmed` flag is set here because the view calls these only after the owner has said yes in its own question.
 */
export function createTrashTransport(
  call: RoomTransport["call"],
  supportsTool?: RoomTransport["supportsTool"],
): TrashTransport {
  return {
    trash: (cursor) =>
      call<TrashList>("list_trash", cursor === undefined ? {} : { cursor }),
    restore: (item, key) =>
      call("restore_from_trash", {
        kind: item.kind,
        record_id: item.id,
        version: item.version,
        idempotency_key: key,
      }),
    ...(supportsTool?.(ERASE_TOOL) === true
      ? {
          erase: (item, key) =>
            call(ERASE_TOOL, {
              task_id: item.id,
              version: item.version,
              confirmed: true,
              idempotency_key: key,
            }),
          empty: (key) =>
            call<EmptyResult>("empty_trash", {
              confirmed: true,
              idempotency_key: key,
            }),
        }
      : {}),
  };
}
