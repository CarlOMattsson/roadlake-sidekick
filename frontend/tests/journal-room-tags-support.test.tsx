import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { JournalRoom } from "@/features/journal-app/room";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { day, entry, entryId } from "./helpers/journal-app-fixtures";
import { VOCABULARY } from "./helpers/journal-tag-fixtures";

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
      if (name === "list_tags") return Promise.resolve({ tags: VOCABULARY });
      if (name === "get_journal_day")
        return Promise.resolve(day("2026-10-24", [entry]));
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

const names = (call: ReturnType<typeof hostOf>["call"]) =>
  call.mock.calls.map(([name]) => name);

describe("the Journal room offers tags only where the host answers them", () => {
  it("edits the tags of an entry where the host answers everything", async () => {
    const { call, transport } = hostOf({});
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: entryId } }}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Add tag" }),
    ).toBeInTheDocument();
    expect(names(call)).toContain("list_tags");
  });

  it("calls neither list_tags nor the tag write, and draws no editing, on a host that answers neither (the phone)", async () => {
    const { call, transport } = hostOf({
      supportsTool: (name) => name !== "list_tags",
      supportsCall: (_name, args) => !("tags" in args),
    });
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={{ entry: { id: entryId } }}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: entry.title });
    expect(screen.queryByRole("button", { name: /tag/i })).toBeNull();
    expect(names(call)).not.toContain("list_tags");
  });

  it("draws no filter on the day when the host answers no tagged read", async () => {
    const { call, transport } = hostOf({
      supportsCall: (_name, args) => !("tags" in args),
    });
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={day("2026-10-24", [entry])}
      />,
    );
    await screen.findByRole("heading", { name: "Entries" });
    expect(screen.queryByRole("group", { name: "Filter by tag" })).toBeNull();
    expect(call.mock.calls.every(([, args]) => !(args && "tags" in args))).toBe(
      true,
    );
  });

  it("draws the filter on the day where the host answers it", async () => {
    const { transport } = hostOf({});
    render(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={day("2026-10-24", [entry])}
      />,
    );
    expect(
      await screen.findByRole("group", { name: "Filter by tag" }),
    ).toBeInTheDocument();
  });
});
