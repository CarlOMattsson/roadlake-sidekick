import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ControlRoom } from "@/features/control-app/room";
import type { ChangesList } from "@/features/control-app/transport";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";

// The room is mounted with a trash answer, so it starts on Trash. The tests choose Changes first.
const trashResult = { items: [], has_more: false, next_cursor: null };

const first: ChangesList = {
  changes: [
    {
      kind: "shopping_item",
      id: "019f0000-0000-7000-8000-0000000003a1",
      title: "Mjölk",
      version: 2,
      action: "purchased",
      state: "active",
      occurred_at: "2026-10-31T13:30:00Z",
      undo_tool: "set_shopping_item_purchased",
    },
  ],
};

const second: ChangesList = {
  changes: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000003b1",
      title: "Ring Anna",
      version: 3,
      action: "updated",
      state: "active",
      occurred_at: "2026-11-01T08:05:00Z",
    },
  ],
};

type Call = (name: string, args: object) => Promise<unknown>;

/** The room's props with one shared `call`, so each test routes the reads by tool name. */
function roomProps(call: ReturnType<typeof vi.fn<Call>>, refreshKey?: number) {
  const props: RoomProps = {
    // Module-level constants keep their identity, so a re-render is not a new result.
    initial: trashResult,
    resultId: 1,
    mode: "inline",
    refreshKey,
    transport: {
      call: call as RoomTransport["call"],
      requestDisplayMode: vi.fn(),
      updateModelContext: vi.fn(),
    },
  };
  return props;
}

function readsOf(call: ReturnType<typeof vi.fn<Call>>, name: string) {
  return call.mock.calls.filter(([tool]) => tool === name).length;
}

describe("Control room refresh", () => {
  it("reads the visible history view again in place when refreshKey changes", async () => {
    const call = vi.fn<Call>((name) =>
      name === "list_recent_changes"
        ? Promise.resolve(first)
        : Promise.reject(new Error(`unexpected ${name}`)),
    );
    const user = userEvent.setup();
    const { rerender } = render(<ControlRoom {...roomProps(call, 0)} />);

    await user.click(screen.getByRole("button", { name: "Historik" }));
    expect(await screen.findByText("Mjölk")).toBeInTheDocument();
    expect(readsOf(call, "list_recent_changes")).toBe(1);

    // The second read is held back, so the view must still show the first answer while it is out.
    let answer!: (value: ChangesList) => void;
    call.mockImplementation((name) =>
      name === "list_recent_changes"
        ? new Promise<ChangesList>((resolve) => {
            answer = resolve;
          })
        : Promise.reject(new Error(`unexpected ${name}`)),
    );
    rerender(<ControlRoom {...roomProps(call, 1)} />);

    expect(readsOf(call, "list_recent_changes")).toBe(2);
    expect(screen.getByRole("button", { name: "Historik" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Mjölk")).toBeInTheDocument();

    await act(async () => {
      answer(second);
      await Promise.resolve();
    });
    expect(await screen.findByText("Ring Anna")).toBeInTheDocument();
    expect(screen.queryByText("Mjölk")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Historik" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(readsOf(call, "list_trash")).toBe(0);
  });

  it("does not read again when the same refreshKey is rendered once more", async () => {
    const call = vi.fn<Call>((name) =>
      name === "list_recent_changes"
        ? Promise.resolve(first)
        : Promise.reject(new Error(`unexpected ${name}`)),
    );
    const user = userEvent.setup();
    const { rerender } = render(<ControlRoom {...roomProps(call, 0)} />);

    await user.click(screen.getByRole("button", { name: "Historik" }));
    expect(await screen.findByText("Mjölk")).toBeInTheDocument();

    rerender(<ControlRoom {...roomProps(call, 0)} />);
    expect(readsOf(call, "list_recent_changes")).toBe(1);
    expect(screen.getByText("Mjölk")).toBeInTheDocument();
  });
});
