// The journal room counts "today" in the owner's zone, never the device's. The clock is set to 23:30 UTC,
// which is already the next calendar day in Stockholm (the declared default) and still the same day in New York.
// The room is driven with a plain RoomTransport; no bridge is mocked.
import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { JournalRoom } from "@/features/journal-app/room";
import type { JournalDay } from "@/features/journal-app/transport";
import type { RoomTransport } from "@/features/mcp-apps/room-types";
import { HostToolError } from "@/features/mcp-apps/bridge";

function hostWith(answer: () => Promise<unknown>) {
  const call = vi.fn((name: string) =>
    name === "get_journal_day"
      ? answer()
      : Promise.reject(new Error(`unexpected ${name}`)),
  );
  const transport = {
    call,
    requestDisplayMode: vi.fn().mockResolvedValue("inline"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  } as unknown as RoomTransport;
  return { call, transport };
}

/** A day just before the year turns, so the heading names its year only when it is not in today's year. */
function dayOf(zone?: string): JournalDay {
  return {
    journal_date: "2026-12-30",
    entries: [],
    next_cursor: null,
    summary: { journal_date: "2026-12-30", exists: false, status: "missing" },
    ...(zone ? { owner_timezone: zone } : {}),
  } as unknown as JournalDay;
}

beforeEach(() => {
  document.head.innerHTML = '<meta name="sidekick-app-locale" content="en">';
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-12-31T23:30:00Z"));
});

afterEach(() => vi.useRealTimers());

describe("journal room: today in the owner's zone", () => {
  it("opens on the owner's date, not the device's, when it reads today itself", async () => {
    const { call, transport } = hostWith(() =>
      Promise.reject(new HostToolError("not_found")),
    );
    render(<JournalRoom mode="full" transport={transport} />);

    await screen.findByText("Nothing written yet today.");
    expect(call).toHaveBeenCalledWith("get_journal_day", {
      journal_date: "2027-01-01",
      include_content: true,
      limit: 50,
    });
  });

  it("uses the zone the day names for the glance's today", () => {
    const { transport } = hostWith(() => Promise.resolve(dayOf()));
    const { unmount } = render(
      <JournalRoom
        mode="inline"
        transport={transport}
        initial={dayOf("America/New_York")}
      />,
    );
    // New York is still on 2026-12-31: the 30th is in today's year, so the heading has no year.
    expect(screen.getByRole("heading", { level: 2 })).not.toHaveTextContent(
      "2026",
    );
    unmount();

    render(
      <JournalRoom mode="inline" transport={transport} initial={dayOf()} />,
    );
    // The declared Stockholm zone is already in 2027, so the 30th names its year.
    expect(screen.getByRole("heading", { level: 2 })).toHaveTextContent("2026");
  });
});
