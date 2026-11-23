import type { RoomTransport } from "../../mcp-apps/room-types";
import { toolOffered } from "../../mcp-apps/tool-support";
import type { StartHome } from "./model";

/**
 * The home view's read and its one write, each an existing tool called through the room's transport (the host's
 * tools/call): no credential and no request of the app's own. `offered` is false where the host cannot answer
 * get_start, and the room then opens on the suggestion inbox as before. Skipping a ready conversation is offered only
 * where the host has skip_ready_conversation.
 */
export type HomeTransport = {
  offered: boolean;
  read: () => Promise<StartHome>;
  skip?: (id: string, undo: boolean, key: string) => Promise<unknown>;
};

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
  };
}
