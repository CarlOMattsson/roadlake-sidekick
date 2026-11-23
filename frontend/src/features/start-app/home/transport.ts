import type { RoomTransport } from "../../mcp-apps/room-types";
import { toolOffered } from "../../mcp-apps/tool-support";
import type { ToolResults } from "@/lib/mcp/tool-results.generated";
import type { StartHome } from "./model";

/** What update_task answers: the Task as the server holds it now. */
export type TaskReply = ToolResults["update_task"];

/**
 * The home view's reads and writes, each an existing tool called through the room's transport (the host's
 * tools/call): no credential and no request of the app's own. `offered` is false where the host cannot answer
 * get_start, and the room then opens on the suggestion inbox as before. Skipping a ready conversation is offered only
 * where the host has skip_ready_conversation. Ticking a Task of today done is update_task with the status "completed"
 * against the row's version, as the Agenda's ring writes it; `reopen` (Ångra) is offered only where the host also
 * writes a done Task back to "todo".
 */
export type HomeTransport = {
  offered: boolean;
  read: () => Promise<StartHome>;
  skip?: (id: string, undo: boolean, key: string) => Promise<unknown>;
  complete?: (id: string, version: number, key: string) => Promise<TaskReply>;
  reopen?: (id: string, version: number, key: string) => Promise<unknown>;
};

const statusChange = (
  id: string,
  version: number,
  key: string,
  status: "completed" | "todo",
) => ({
  task_id: id,
  version,
  idempotency_key: key,
  changes: { status },
});

export function createHomeTransport(transport: RoomTransport): HomeTransport {
  const { call } = transport;
  return {
    offered: toolOffered(transport, "get_start"),
    read: () => call<StartHome>("get_start", {}),
    ...(toolOffered(transport, "skip_ready_conversation")
      ? {
          skip: (id: string, undo: boolean, key: string) =>
            call("skip_ready_conversation", {
              conversation_id: id,
              idempotency_key: key,
              ...(undo ? { undo: true } : {}),
            }),
        }
      : {}),
    ...(toolOffered(transport, "update_task", {
      changes: { status: "completed" },
    })
      ? {
          complete: (id: string, version: number, key: string) =>
            call<TaskReply>(
              "update_task",
              statusChange(id, version, key, "completed"),
            ),
        }
      : {}),
    ...(toolOffered(transport, "update_task", {
      changes: { status: "todo" },
      from_status: "completed",
    })
      ? {
          reopen: (id: string, version: number, key: string) =>
            call("update_task", statusChange(id, version, key, "todo")),
        }
      : {}),
  };
}
