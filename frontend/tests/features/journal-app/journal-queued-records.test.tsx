import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { EntryCard } from "@/features/journal-app/entry-card";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalRoom } from "@/features/journal-app/room";
import type { JournalTransport } from "@/features/journal-app/transport";
import { useQueuedRecords } from "@/features/journal-app/use-queued-records";
import type {
  OfflineSupport,
  RoomTransport,
} from "@/features/mcp-apps/room-types";
import { day, entry, entryId } from "@tests/helpers/journal-app-fixtures";

const STAND_IN = {
  ...entry,
  id: "queued-abc123",
  title: "Skrivet utan nät",
  summary: null,
};

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
});
afterEach(() => {
  document.head.innerHTML = "";
});

/** The phone's outbox: the ids it answers with, and a way to say a run of it ended. */
function outbox(ids: string[]) {
  const listeners: Array<() => void> = [];
  let current = ids;
  const offline: OfflineSupport = {
    readAt: () => undefined,
    queuedPurchases: () => Promise.resolve(new Map()),
    queuedRecordIds: vi.fn(() => Promise.resolve(new Set(current))),
    onQueueChanged: vi.fn((listener: () => void) => {
      listeners.push(listener);
      return () => undefined;
    }),
  };
  return {
    offline,
    finish: (next: string[]) => {
      current = next;
      listeners.forEach((listener) => listener());
      return Promise.resolve();
    },
  };
}

function host(offline?: RoomTransport["offline"]) {
  const call = vi.fn<(name: string, args?: object) => Promise<unknown>>(
    (name) => {
      if (name === "get_journal_entry") return Promise.resolve({ entry });
      if (name === "get_journal_day")
        return Promise.resolve(day("2026-10-24", [STAND_IN, entry]));
      return Promise.reject(new Error(`unexpected ${name}`));
    },
  );
  return {
    call,
    transport: {
      call,
      requestDisplayMode: vi.fn().mockResolvedValue("fullscreen"),
      updateModelContext: vi.fn().mockResolvedValue(undefined),
      ...(offline ? { offline } : {}),
    } as unknown as RoomTransport,
  };
}

describe("useQueuedRecords", () => {
  it("is empty without an outbox (Claude)", () => {
    const { result } = renderHook(() => useQueuedRecords({}));
    expect(result.current.size).toBe(0);
  });

  it("reads the outbox, and again every time a run of it ends", async () => {
    const box = outbox(["queued-a"]);
    const transport: Pick<JournalTransport, "offline"> = {
      offline: box.offline,
    };
    const { result } = renderHook(() => useQueuedRecords(transport));
    await act(() => Promise.resolve());
    expect([...result.current]).toEqual(["queued-a"]);
    await act(() => box.finish([]));
    await waitFor(() => expect(result.current.size).toBe(0));
    expect(box.offline.queuedRecordIds).toHaveBeenCalledTimes(2);
  });
});

describe("a note that waits in the phone's outbox", () => {
  it("is drawn as waiting on its row in the day view, and is not opened", async () => {
    const box = outbox(["queued-abc123", entryId]);
    render(
      <JournalRoom
        mode="full"
        transport={host(box.offline).transport}
        initial={day("2026-10-24", [STAND_IN, entry])}
      />,
    );
    await screen.findByText("Skrivet utan nät");
    expect(await screen.findAllByText("Waiting…")).toHaveLength(2);
    // The stand-in has no entry on the server yet, so its row is plain content; the sent entry still opens.
    expect(
      screen.queryByRole("button", { name: /Skrivet utan nät/ }),
    ).toBeNull();
    expect(
      screen.getByRole("button", { name: /Mötet om offerten/ }),
    ).toBeInTheDocument();
  });

  it("is drawn as waiting in the entry view of an edited entry", async () => {
    const box = outbox([entryId]);
    render(
      <JournalRoom
        mode="full"
        transport={host(box.offline).transport}
        initial={{ entry: { id: entryId } }}
      />,
    );
    expect(await screen.findByText("Waiting…")).toBeInTheDocument();
    await act(() => box.finish([]));
    await waitFor(() => expect(screen.queryByText("Waiting…")).toBeNull());
  });

  it("draws nothing where the host has no outbox", async () => {
    render(
      <JournalRoom
        mode="full"
        transport={host().transport}
        initial={day("2026-10-24", [entry])}
      />,
    );
    await screen.findByText("Mötet om offerten");
    expect(screen.queryByText("Waiting…")).toBeNull();
  });
});

describe("the inline entry card", () => {
  it.each([
    ["en", journalEn, "Waiting…"],
    ["sv", journalSv, "Väntar…"],
  ])("says the entry waits (%s)", (_name, labels, text) => {
    render(
      <EntryCard
        entry={STAND_IN}
        today="2026-10-24"
        labels={labels}
        onOpen={() => undefined}
        queued
      />,
    );
    expect(screen.getByText(text)).toHaveClass("sk-queued");
  });

  it("says nothing for an entry that is not waiting", () => {
    render(
      <EntryCard
        entry={entry}
        today="2026-10-24"
        labels={journalEn}
        onOpen={() => undefined}
      />,
    );
    expect(screen.queryByText("Waiting…")).toBeNull();
  });
});
