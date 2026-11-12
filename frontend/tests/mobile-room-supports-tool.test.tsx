import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  RoomAdapter,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";
import type { ShellRoomProps } from "@/features/mcp-apps/sidekick-shell";

afterEach(cleanup);

/** A room that shows a menu item only for the tools its transport can answer. */
function ProbeRoom({ transport }: RoomProps) {
  const offers = (tool: string) => transport.supportsTool?.(tool) ?? true;
  return (
    <ul>
      {offers("list_saved_work_views") ? <li>Sparade vyer</li> : null}
      {offers("get_work_agenda") ? <li>Uppdatera</li> : null}
    </ul>
  );
}

const SHELL: ShellRoomProps = {
  entry: { room: "work", view: "agenda" },
  full: true,
  visible: true,
  refreshKey: 0,
  markDirty: () => undefined,
  locale: "sv",
};

function mount(supportsTool?: (name: string) => boolean) {
  const transport: RoomTransport = {
    call: () => Promise.resolve({} as never),
    requestDisplayMode: () => Promise.resolve("fullscreen"),
    updateModelContext: () => Promise.resolve(),
    ...(supportsTool ? { supportsTool } : {}),
  };
  const host: RoomHost = {
    transport,
    fullscreenAvailable: () => false,
    onExpand: () => undefined,
  };
  return render(
    <RoomHostContext.Provider value={host}>
      <RoomAdapter Room={ProbeRoom} shell={SHELL} />
    </RoomHostContext.Provider>,
  );
}

describe("RoomAdapter and supportsTool", () => {
  it("lets a room see the host's closed tool list", () => {
    mount((name) => name === "get_work_agenda");
    expect(screen.queryByText("Sparade vyer")).toBeNull();
    expect(screen.getByText("Uppdatera")).toBeInTheDocument();
  });

  it("leaves every tool open on a host without a list (Claude)", () => {
    mount();
    expect(screen.getByText("Sparade vyer")).toBeInTheDocument();
    expect(screen.getByText("Uppdatera")).toBeInTheDocument();
  });
});
