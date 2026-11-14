import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ControlRoom } from "@/features/control-app/room";
import type { MemoryStatus } from "@/features/control-app/transport";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";

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

type Call = (name: string, args: object) => Promise<unknown>;

/** A room mounted by a "Minne och kontroll" menu entry: no tool result, only the view the entry named. */
function hiddenProps(call: ReturnType<typeof vi.fn<Call>>, view?: string) {
  const props: RoomProps = {
    mode: "full",
    view,
    transport: {
      call: call as RoomTransport["call"],
      requestDisplayMode: vi.fn(),
      updateModelContext: vi.fn(),
    },
  };
  return props;
}

function answer(name: string): Promise<unknown> {
  if (name === "get_memory_status") return Promise.resolve(memory);
  if (name === "list_trash")
    return Promise.resolve({ items: [], has_more: false, next_cursor: null });
  return Promise.reject(new Error(`unexpected ${name}`));
}

describe("Control room start view", () => {
  it("opens on the memory tab and reads the memory, not the trash, when the entry names memory", async () => {
    const call = vi.fn<Call>((name) => answer(name));
    render(<ControlRoom {...hiddenProps(call, "memory")} />);

    expect(
      await screen.findByRole("heading", { name: "Minnet är på" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Sidekicks minne", pressed: true }),
    ).toBeInTheDocument();
    expect(call.mock.calls.map(([name]) => name)).toEqual([
      "get_memory_status",
    ]);
  });

  it("opens on the trash when no view, or an unknown one, is named", async () => {
    const call = vi.fn<Call>((name) => answer(name));
    const { unmount } = render(<ControlRoom {...hiddenProps(call)} />);
    expect(
      await screen.findByRole("button", { name: "Borttaget", pressed: true }),
    ).toBeInTheDocument();
    unmount();
    render(<ControlRoom {...hiddenProps(call, "nonsense")} />);
    expect(
      await screen.findByRole("button", { name: "Borttaget", pressed: true }),
    ).toBeInTheDocument();
    expect(call).toHaveBeenCalledWith("list_trash", {});
  });
});

describe("Control room, a failed answer of the history tools", () => {
  it.each(["changes", "activity"])(
    "opens on History, names it, and reads the history again (not the trash) on Try again (%s)",
    async (view) => {
      const call = vi.fn<Call>((name) =>
        name === "list_recent_changes"
          ? Promise.resolve({ changes: [] })
          : name === "list_assistant_activity"
            ? Promise.resolve({ items: [], next_cursor: null })
            : answer(name),
      );
      render(
        <ControlRoom
          {...hiddenProps(call, view)}
          initialError
          initial={undefined}
          resultId={1}
        />,
      );

      expect(await screen.findByRole("alert")).toHaveTextContent(
        "Historiken kunde inte hämtas",
      );
      await userEvent.click(
        screen.getByRole("button", { name: "Försök igen" }),
      );
      expect(
        await screen.findByRole("button", { name: "Historik", pressed: true }),
      ).toBeInTheDocument();
      expect(call.mock.calls.map(([name]) => name).sort()).toEqual([
        "list_assistant_activity",
        "list_recent_changes",
      ]);
    },
  );
});
