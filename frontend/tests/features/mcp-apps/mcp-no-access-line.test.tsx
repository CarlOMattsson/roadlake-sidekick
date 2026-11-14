import { act, cleanup, render, screen } from "@testing-library/react";
import { useEffect } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  RoomAdapter,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import type { ShellRoomProps } from "@/features/mcp-apps/sidekick-shell";
import { ROOT_VIEW } from "@/features/mcp-apps/nav-state";
import type { RoomProps } from "@/features/mcp-apps/room-types";

// A host whose every tools/call is refused with the given error code.
function failingHost(code: string | undefined) {
  const call = vi.fn((name: string, args: object): Promise<never> => {
    void name;
    void args;
    return Promise.reject(new HostToolError(code));
  });
  const host: RoomHost = {
    transport: {
      call: call,
      requestDisplayMode: vi.fn().mockResolvedValue("inline"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
    },
    fullscreenAvailable: () => false,
    onExpand: vi.fn(),
  };
  return { call, host };
}

// A room that reads once on mount and ignores the failure, as the real rooms do.
function ReadingRoom({ transport }: RoomProps) {
  useEffect(() => {
    transport.call("get_task", {}).catch(() => undefined);
  }, [transport]);
  return <p>Rumsinnehåll</p>;
}

const shell: ShellRoomProps = {
  entry: { room: "work", view: ROOT_VIEW },
  full: true,
  visible: true,
  refreshKey: 0,
  markDirty: () => undefined,
  locale: "sv",
};

function renderRoom(code: string | undefined) {
  const { call, host } = failingHost(code);
  render(
    <RoomHostContext.Provider value={host}>
      <RoomAdapter Room={ReadingRoom} shell={shell} />
    </RoomHostContext.Provider>,
  );
  return call;
}

afterEach(() => {
  cleanup();
});

it("shows the calm no-access line when the server refuses the first read, and the room does not crash", async () => {
  const call = renderRoom("forbidden");
  const line = await screen.findByRole("status");
  expect(line).toHaveTextContent(
    "Sidekick-anslutningen har inte tillgång till Arbete.",
  );
  expect(call).toHaveBeenCalledWith("get_task", {});
});

it("shows no access line for an error that is not a refusal of access", async () => {
  const call = renderRoom("internal");
  expect(await screen.findByText("Rumsinnehåll")).toBeInTheDocument();
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
  expect(call).toHaveBeenCalledWith("get_task", {});
  expect(screen.queryByRole("status")).toBeNull();
});
