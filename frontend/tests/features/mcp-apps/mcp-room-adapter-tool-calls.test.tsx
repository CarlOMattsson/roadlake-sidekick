import { cleanup, render } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  RoomAdapter,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import type { ShellRoomProps } from "@/features/mcp-apps/sidekick-shell";
import type { RoomProps } from "@/features/mcp-apps/room-types";

// What the adapter tells a room about the host's tool calls. A simulated host (a fake transport and a stand-in room), not
// a real Claude or Android host.

afterEach(cleanup);

function hostWith(toolCalls?: () => boolean): RoomHost {
  return {
    transport: {
      call: vi.fn(),
      requestDisplayMode: vi.fn().mockResolvedValue("inline"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
    },
    fullscreenAvailable: () => false,
    onExpand: vi.fn(),
    toolCalls,
  };
}

const shell: ShellRoomProps = {
  entry: { room: "work", view: "agenda" },
  full: false,
  visible: true,
  refreshKey: 0,
  markDirty: vi.fn(),
  locale: "en",
};

/** The `toolCalls` prop the room got from the adapter for a host. */
function seenBy(host: RoomHost): RoomProps["toolCalls"] {
  let seen: RoomProps["toolCalls"] = "unset" as never;
  function Probe(props: RoomProps) {
    seen = props.toolCalls;
    return null;
  }
  render(
    <RoomHostContext.Provider value={host}>
      <RoomAdapter Room={Probe} shell={shell} />
    </RoomHostContext.Provider>,
  );
  return seen;
}

describe("RoomAdapter toolCalls", () => {
  it("passes false when the host does not let the app call tools", () => {
    expect(seenBy(hostWith(() => false))).toBe(false);
  });

  it("passes true when the host does, and when it says nothing", () => {
    expect(seenBy(hostWith(() => true))).toBe(true);
    cleanup();
    expect(seenBy(hostWith())).toBe(true);
  });
});
