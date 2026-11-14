import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ControlRoom } from "@/features/control-app/room";
import type { MemoryStatus, TrashList } from "@/features/control-app/transport";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";
import { deferred } from "@tests/helpers/deferred";

/*
 * A late answer must not put what it saw back over what a newer tool result has put there since.
 */

const memory: MemoryStatus = {
  settings: {
    journal: true,
    contacts: true,
    projects: false,
    tasks: true,
    paused: false,
    version: 3,
  },
  provider: "hindsight",
  sources: [],
};

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("the Control room: Try again that answers after a newer result", () => {
  it("keeps the card of the newer tool result", async () => {
    const user = userEvent.setup();
    const retryRead = deferred<TrashList>();
    const call = vi.fn((name: string) =>
      name === "list_trash"
        ? retryRead.promise
        : Promise.reject(new Error(`unexpected ${name}`)),
    );
    const props = (extra: Partial<RoomProps>): RoomProps => ({
      mode: "full",
      transport: {
        call: call as RoomTransport["call"],
        requestDisplayMode: vi.fn(),
        updateModelContext: vi.fn(),
      },
      ...extra,
    });
    const { rerender } = render(
      <ControlRoom {...props({ initialError: true, resultId: 1 })} />,
    );
    await user.click(await screen.findByRole("button", { name: "Try again" }));
    expect(call).toHaveBeenCalledWith("list_trash", {});

    // Claude opened the memory view meanwhile, and its result is on screen.
    rerender(<ControlRoom {...props({ initial: memory, resultId: 2 })} />);
    expect(
      await screen.findByRole("heading", { name: "Memory is on" }),
    ).toBeInTheDocument();

    await act(async () => {
      retryRead.resolve({ items: [], has_more: false, next_cursor: null });
      await retryRead.promise;
    });
    expect(
      screen.getByRole("heading", { name: "Memory is on" }),
    ).toBeInTheDocument();
    // The memory card was not rebuilt from the older answer, so it read nothing for itself.
    expect(call).toHaveBeenCalledTimes(1);
  });
});
