import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn } from "@/features/journal-app/labels";
import { JournalRoom } from "@/features/journal-app/room";
import type { JournalTaggedPage } from "@/features/journal-app/tag-transport";
import type { JournalEntry } from "@/features/journal-app/transport";
import { HostToolError } from "@/features/mcp-apps/bridge";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import {
  day,
  entry,
  otherEntry,
  transportMock,
} from "./helpers/journal-app-fixtures";
import { deferred } from "./helpers/deferred";
import { listTagsMock, taggedEntry } from "./helpers/journal-tag-fixtures";

/*
 * Answers that arrive after the view moved on: a slow read must not put what it saw back over what the owner or a
 * newer read has put there since.
 */

function tagged(n: number, journalDate: string): JournalEntry {
  return taggedEntry(["viktig"], {
    id: `019f0000-0000-7000-8000-00000000f${n}`,
    title: `Post ${n}`,
    journal_date: journalDate,
    occurred_at: null,
    summary: null,
  });
}

const page = (entries: JournalEntry[]): JournalTaggedPage => ({
  entries,
  next_cursor: null,
});

describe("the tagged list: Show more that answers after a refresh", () => {
  it("drops the older year when the last 12 months were read again meanwhile", async () => {
    const user = userEvent.setup();
    const older = deferred<JournalTaggedPage>();
    const listTaggedEntries = vi
      .fn()
      .mockResolvedValueOnce(page([tagged(1, "2026-09-30")]))
      .mockReturnValueOnce(older.promise)
      .mockResolvedValueOnce(page([tagged(3, "2026-10-02")]));
    const transport = transportMock({
      listTags: listTagsMock(),
      listTaggedEntries,
    });
    const initial = { kind: "day" as const, page: day("2026-10-24", [entry]) };
    const view = (refreshKey: number) => (
      <JournalView
        transport={transport}
        initial={initial}
        labels={journalEn}
        refreshKey={refreshKey}
      />
    );
    const { rerender } = render(view(0));
    await user.click(await screen.findByRole("button", { name: "Viktig" }));
    await screen.findByText("Post 1");

    await user.click(
      screen.getByRole("button", { name: journalEn.taggedMore }),
    );
    rerender(view(1));
    await screen.findByText("Post 3");

    await act(async () => {
      older.resolve(page([tagged(2, "2025-06-01")]));
      await older.promise;
    });
    expect(screen.getByText("Post 3")).toBeInTheDocument();
    // The older answer was asked for the list as it was; it must not bring that list back.
    expect(screen.queryByText("Post 1")).not.toBeInTheDocument();
    expect(screen.queryByText("Post 2")).not.toBeInTheDocument();
  });
});

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});

describe("the journal room: Try again that answers after a newer result", () => {
  it("keeps the day of the newer tool result", async () => {
    const user = userEvent.setup();
    const retryRead = deferred<unknown>();
    const readDay = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockReturnValueOnce(retryRead.promise);
    const call = vi.fn((name: string) =>
      name === "get_journal_day"
        ? (readDay() as Promise<unknown>)
        : Promise.reject(new Error(`unexpected ${name}`)),
    );
    const transport = {
      call,
      requestDisplayMode: vi.fn().mockResolvedValue("inline"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
    } as unknown as RoomTransport;
    const room = (props: { resultId?: number; initial?: unknown }) => (
      <JournalRoom mode="full" transport={transport} {...props} />
    );
    const { rerender } = render(room({}));
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: "Try again" }));
    expect(readDay).toHaveBeenCalledTimes(2);

    // The owner asked Claude for another day meanwhile, and its result is on screen.
    rerender(room({ resultId: 1, initial: day("2026-10-20", [entry]) }));
    expect(await screen.findByText(entry.title)).toBeInTheDocument();

    await act(async () => {
      retryRead.resolve(day("2026-10-24", [otherEntry]));
      await retryRead.promise;
    });
    expect(screen.getByText(entry.title)).toBeInTheDocument();
    expect(screen.queryByText(otherEntry.title)).not.toBeInTheDocument();
  });
});
