/**
 * The Journal room's one memory call: keeping an entry out of Claude's memory, or bringing it back
 * (exclude_from_memory). Offered only where the host answers it; the transport leaves it out otherwise.
 */
import type { ToolResults } from "../../lib/mcp/tool-results.generated";
import type { RoomTransport } from "../mcp-apps/room-types";

export type MemoryTransport = {
  /**
   * Keeps the entry out of Claude's memory, or brings it back. The entry's version does not change. Optional:
   * without it the entry's menu offers no such item.
   */
  excludeEntryFromMemory?: (
    entryId: string,
    excluded: boolean,
  ) => Promise<unknown>;
};

/** The memory call over the host's tools/call, or nothing when the host does not answer it. */
export function createMemoryTransport(
  call: RoomTransport["call"],
  enabled: boolean,
): MemoryTransport {
  if (!enabled) return {};
  return {
    excludeEntryFromMemory: (entryId, excluded) =>
      call<ToolResults["exclude_from_memory"]>("exclude_from_memory", {
        kind: "journal_entry",
        id: entryId,
        excluded,
      }),
  };
}
