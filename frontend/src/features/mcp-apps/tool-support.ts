import { useCallback } from "react";
import type { RoomTransport } from "./room-types";

/** The two optional questions a host can answer about its tools (RoomTransport.supportsTool and .supportsCall). */
export type ToolSupport = Pick<RoomTransport, "supportsTool" | "supportsCall">;

/**
 * Whether the host answers a tool, so a room offers no button, menu item or link whose tool is missing. Absent
 * `host` or absent questions (the Claude host proxies the whole server): every tool. `args` names the call for a tool
 * the host answers only in part, e.g. update_task with `{ changes: { status: "completed" } }`.
 */
export function toolOffered(
  host: ToolSupport | undefined,
  name: string,
  args?: object,
): boolean {
  if (host?.supportsTool?.(name) === false) return false;
  if (args !== undefined && host?.supportsCall)
    return host.supportsCall(name, args);
  return true;
}

/** `toolOffered` for one host, as a function a component keeps for its render. */
export function useToolSupport(
  host: ToolSupport | undefined,
): (name: string, args?: object) => boolean {
  return useCallback(
    (name: string, args?: object) => toolOffered(host, name, args),
    [host],
  );
}
