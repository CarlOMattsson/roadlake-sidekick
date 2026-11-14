// The journal room inside the Sidekick shell: with onNavigate, entries, drafts and originals open through
// the shell (no inner Back, no "Show summary" line); without it they open inline as before. The room also
// reads again in place when its refreshKey changes, keeping the shown day and entry. The room is driven
// with a plain RoomTransport; no bridge is mocked.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi, type Mock } from "vitest";

import { journalEn } from "@/features/journal-app/labels";
import { JournalRoom } from "@/features/journal-app/room";
import {
  rootFromToolResult,
  type JournalDay,
  type JournalEntry,
  type JournalSource,
} from "@/features/journal-app/transport";
import type { RoomProps, RoomTransport } from "@/features/mcp-apps/room-types";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const sourceId = "019f0000-0000-7000-8000-0000000000s1";
const draftId = "019f0000-0000-7000-8000-0000000000d1";
const taskA = "019f0000-0000-7000-8000-0000000000t1";
const taskB = "019f0000-0000-7000-8000-0000000000t2";
const rawText = "Råtext: Anna vill ha offerten före fredag.";

const entry: JournalEntry = {
  id: entryId,
  source_id: sourceId,
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 1,
};

const source: JournalSource = {
  id: sourceId,
  source_type: "manual_text",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  source_recorded_at: "2026-10-24T09:31:00Z",
  language: "sv",
  created_at: "2026-10-24T09:31:00Z",
  raw_text: rawText,
};

const dayPage: JournalDay = {
  journal_date: "2026-10-24",
  entries: [entry],
  next_cursor: null,
  summary: {
    journal_date: "2026-10-24",
    exists: true,
    status: "current",
    content: { overview: "Dagen handlade om offerten." },
  },
};

// The results the rooms receive are held as constants: a new object would count as a new result.
const dayResult = dayPage;
const entryResult = { entry: { id: entryId } };
const sourceResult = { source: { id: sourceId } };

/** The host's answers to the reads the room makes; anything else is refused. */
function answerFor(name: string): Promise<unknown> {
  if (name === "get_journal_day") return Promise.resolve(dayPage);
  if (name === "get_journal_entry") return Promise.resolve({ entry });
  if (name === "get_journal_source") return Promise.resolve({ source });
  return Promise.reject(new Error(`unexpected ${name}`));
}

function hostFor(): { call: Mock; transport: RoomTransport } {
  const call = vi.fn((name: string) => answerFor(name));
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("inline"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomTransport;
  return { call, transport };
}

function renderRoom(
  transport: RoomTransport,
  props: Omit<Partial<RoomProps>, "transport" | "mode"> = {},
) {
  return render(<JournalRoom mode="full" transport={transport} {...props} />);
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("journal room: drill-ins through the shell's navigation", () => {
  it("opens an entry of the day through onNavigate and draws no inner Back", async () => {
    const { call, transport } = hostFor();
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    renderRoom(transport, { initial: dayResult, onNavigate });

    await user.click(screen.getByRole("button", { name: /Mötet om offerten/ }));

    expect(onNavigate).toHaveBeenCalledTimes(1);
    expect(onNavigate).toHaveBeenCalledWith({
      room: "journal",
      view: "entry",
      id: entryId,
    });
    expect(document.querySelector(".journal-back")).toBeNull();
    expect(call).not.toHaveBeenCalledWith(
      "get_journal_entry",
      expect.anything(),
    );
  });

  it("opens the entry inline with its own Back when no onNavigate is given", async () => {
    const { call, transport } = hostFor();
    const user = userEvent.setup();
    renderRoom(transport, { initial: dayResult });

    await user.click(screen.getByRole("button", { name: /Mötet om offerten/ }));

    await screen.findByRole("heading", { level: 2, name: entry.title });
    expect(screen.getByRole("button", { name: journalEn.back })).toHaveClass(
      "journal-back",
    );
    expect(call).toHaveBeenCalledWith("get_journal_entry", {
      entry_id: entryId,
      include_content: true,
    });
  });

  it("opens the original through onNavigate with the source view, not inline", async () => {
    const { transport } = hostFor();
    const onNavigate = vi.fn();
    const user = userEvent.setup();
    renderRoom(transport, { initial: entryResult, onNavigate });

    await user.click(
      await screen.findByRole("button", { name: journalEn.showOriginal }),
    );

    expect(onNavigate).toHaveBeenCalledWith({
      room: "journal",
      view: "source",
      id: sourceId,
    });
    expect(document.querySelector(".journal-original")).toBeNull();
  });

  it("draws the original text of a source the shell routes to the room", async () => {
    const { transport } = hostFor();
    renderRoom(transport, { initial: sourceResult, view: "source" });

    const original = await screen.findByText(rawText);
    expect(original).toHaveClass("journal-original");
  });

  it("shows no Show summary line in a source opened through onNavigate", async () => {
    const { transport } = hostFor();
    renderRoom(transport, { initial: sourceResult, onNavigate: vi.fn() });

    await screen.findByText(rawText);
    expect(
      screen.queryByRole("button", { name: journalEn.showSummary }),
    ).toBeNull();
  });

  it("keeps the Show summary line for a source opened inline", async () => {
    const { transport } = hostFor();
    renderRoom(transport, { initial: sourceResult });

    await screen.findByText(rawText);
    expect(
      screen.getByRole("button", { name: journalEn.showSummary }),
    ).toBeInTheDocument();
  });
});

describe("rootFromToolResult: routed results", () => {
  it("reads an id-only source result as the source root", () => {
    expect(rootFromToolResult(sourceResult)).toEqual({
      kind: "source",
      id: sourceId,
    });
  });

  it("reads a saved draft's entry result with its notice", () => {
    expect(
      rootFromToolResult({
        entry: { id: entryId },
        notice: { created: 2, updated: 1, createdTaskIds: [taskA, taskB] },
      }),
    ).toEqual({
      kind: "entry",
      id: entryId,
      notice: { created: 2, updated: 1, createdTaskIds: [taskA, taskB] },
    });
  });

  it("opens a plain entry result without a notice, and drops a malformed notice", () => {
    expect(rootFromToolResult(entryResult)).not.toHaveProperty("notice");
    expect(
      rootFromToolResult({
        entry: { id: entryId },
        notice: { created: "2", updated: 0 },
      }),
    ).not.toHaveProperty("notice");
  });

  it("reads a draft result as the draft even though it also carries a source", () => {
    expect(
      rootFromToolResult({ draft: { id: draftId }, source: { id: sourceId } }),
    ).toEqual({ kind: "draft", id: draftId });
  });
});

describe("journal room: refresh in place", () => {
  it("reads the shown day again when refreshKey changes, and does not change the day", async () => {
    const { call, transport } = hostFor();
    const { rerender } = renderRoom(transport, {
      initial: dayResult,
      refreshKey: 1,
    });
    // The strip's dates read (list_journal_entries) is not a day read; count only the day reads.
    const named = (name: string) =>
      call.mock.calls.filter(([tool]) => tool === name).length;
    // The value at mount is not a request.
    await waitFor(() => expect(named("list_journal_entries")).toBe(1));
    expect(named("get_journal_day")).toBe(0);

    rerender(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={dayResult}
        refreshKey={2}
      />,
    );

    await waitFor(() => expect(named("get_journal_day")).toBe(1));
    expect(call).toHaveBeenCalledWith(
      "get_journal_day",
      expect.objectContaining({ journal_date: "2026-10-24" }),
    );
    // The refresh reads the strip's dots again too.
    await waitFor(() => expect(named("list_journal_entries")).toBe(2));
    // In place: no loading state, and the entry stays on the day.
    expect(screen.queryByText(journalEn.loading)).toBeNull();
    expect(
      screen.getByRole("button", { name: /Mötet om offerten/ }),
    ).toBeInTheDocument();
  });

  it("reads the shown entry again when refreshKey changes, keeping it on screen", async () => {
    const { call, transport } = hostFor();
    const { rerender } = renderRoom(transport, {
      initial: entryResult,
      refreshKey: 1,
    });
    await screen.findByRole("heading", { level: 2, name: entry.title });
    // The tag vocabulary is read too; the refresh is about the entry.
    const entryReads = () =>
      call.mock.calls.filter(([name]) => name === "get_journal_entry").length;
    expect(entryReads()).toBe(1);

    rerender(
      <JournalRoom
        mode="full"
        transport={transport}
        initial={entryResult}
        refreshKey={2}
      />,
    );

    await waitFor(() => expect(entryReads()).toBe(2));
    expect(screen.queryByText(journalEn.loading)).toBeNull();
    expect(
      screen.getByRole("heading", { level: 2, name: entry.title }),
    ).toBeInTheDocument();
  });
});

describe("journal room: the app name inside the shell", () => {
  it("keeps the app name for assistive technology and hides it from sight when the shell frames the room", () => {
    const { transport } = hostFor();
    render(
      <RoomSurfaceContext.Provider value={{ active: true, framed: true }}>
        <JournalRoom mode="full" transport={transport} initial={dayResult} />
      </RoomSurfaceContext.Provider>,
    );

    const name = screen.getByRole("heading", {
      level: 1,
      name: journalEn.title,
    });
    expect(name).toHaveClass("journal-visually-hidden");
  });

  it("shows the app name when the room is drawn without the shell", () => {
    const { transport } = hostFor();
    renderRoom(transport, { initial: dayResult });

    const name = screen.getByRole("heading", {
      level: 1,
      name: journalEn.title,
    });
    expect(name).not.toHaveClass("journal-visually-hidden");
  });
});
