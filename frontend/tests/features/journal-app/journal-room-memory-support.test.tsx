import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { day, entry, entryId } from "@tests/helpers/journal-app-fixtures";

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterEach(() => {
  document.head.innerHTML = "";
});

function hostOf(extra: Partial<RoomTransport>) {
  const call = vi.fn<(name: string, args?: object) => Promise<unknown>>(
    (name) => {
      if (name === "get_journal_entry") return Promise.resolve({ entry });
      if (name === "get_journal_day")
        return Promise.resolve(day("2026-10-24", [entry]));
      if (name === "exclude_from_memory")
        return Promise.resolve({ changed: true });
      return Promise.reject(new Error(`unexpected ${name}`));
    },
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
    ...extra,
  } as unknown as RoomTransport;
  return { call, transport };
}

async function openMenu() {
  await screen.findByRole("heading", { level: 2, name: entry.title });
  await userEvent.click(
    screen.getByRole("button", { name: "More options for this entry" }),
  );
}

describe("the Journal room offers keeping an entry out of memory only where the host answers it", () => {
  it("offers the item and calls exclude_from_memory where the host answers everything", async () => {
    const { call, transport } = hostOf({});
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: entryId } }}
      />,
    );
    await openMenu();
    await userEvent.click(
      screen.getByRole("button", { name: "Keep out of memory" }),
    );
    expect(
      await screen.findByText(/The entry is kept out of memory/),
    ).toBeVisible();
    expect(call).toHaveBeenCalledWith("exclude_from_memory", {
      kind: "journal_entry",
      id: entryId,
      excluded: true,
    });
  });

  it("leaves the item out on a host without the tool (the phone)", async () => {
    const { transport } = hostOf({
      supportsTool: (name) => name !== "exclude_from_memory",
    });
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: entryId } }}
      />,
    );
    await openMenu();
    expect(
      screen.getByRole("button", { name: "Delete entry" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /memory/i })).toBeNull();
  });
});
