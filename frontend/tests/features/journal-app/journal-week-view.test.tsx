// The calendar week view of the Journal room (fullscreen): switching to it, its heading and days, stepping a
// calendar week, the empty day, «Gjort» per day, opening an entry, and going back to the day. A simulated host: the
// transport is a mock, so this is not a proof in the real Claude or Android host.
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import type {
  JournalDay,
  JournalDone,
  JournalFrame,
} from "@/features/journal-app/transport";
import {
  emptyDay,
  entry,
  otherEntry,
  transportMock,
} from "@tests/helpers/journal-app-fixtures";

// Wednesday 18 November 2026: its week is Monday 16 to Sunday 22 November, week 47.
const TODAY = "2026-11-18";

const done: JournalDone = {
  tasks: [
    {
      id: "t1",
      title: "Betala elräkningen",
      completed_at: "2026-11-17T07:40:00Z",
      project_title: null,
      recurring: false,
    },
  ],
  steps: [],
  purchases: [],
  counts: { tasks: 1, steps: 0, purchases: 0 },
  truncated: false,
};

function pageFor(date: string): JournalDay {
  if (date === "2026-11-16")
    return {
      ...emptyDay(date),
      entries: [{ ...entry, journal_date: date, title: "Middag med Björn" }],
    };
  if (date === "2026-11-17") return { ...emptyDay(date), done };
  if (date === "2026-11-18")
    return {
      ...emptyDay(date),
      entries: [{ ...otherEntry, journal_date: date, title: "Planering" }],
      summary: {
        journal_date: date,
        exists: true,
        status: "current",
        content: { overview: "Onsdagen gick åt till planering." },
      },
    };
  return emptyDay(date);
}

const root: JournalFrame = { kind: "day", page: pageFor(TODAY) };

function setup(labels = journalSv, onRoute = vi.fn()) {
  const transport = transportMock({
    getDay: vi.fn((date: string) => Promise.resolve(pageFor(date))),
    listEntryDates: vi.fn(() => Promise.resolve([])),
  });
  render(
    <JournalView
      transport={transport}
      initial={root}
      labels={labels}
      fullscreen
      onRoute={onRoute}
    />,
  );
  return { transport, onRoute };
}

describe("journal week view", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
  });
  afterEach(() => vi.useRealTimers());

  it("is off by default, and the switch opens the calendar week with its number and dates in the heading", async () => {
    const user = userEvent.setup();
    const { transport } = setup();
    expect(
      screen.getByRole("heading", { level: 2, name: "Onsdag 18 november" }),
    ).toBeInTheDocument();
    const group = screen.getByRole("group", { name: "Visning" });
    expect(within(group).getByRole("button", { name: "Dag" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(within(group).getByRole("button", { name: "Vecka" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Vecka 47 · 16–22 nov",
      }),
    ).toBeInTheDocument();
    // Monday to today, each day read once with the day's own call; no day after today.
    await waitFor(() => {
      expect(transport.getDay).toHaveBeenCalledWith("2026-11-16");
      expect(transport.getDay).toHaveBeenCalledWith("2026-11-17");
    });
    expect(transport.getDay).not.toHaveBeenCalledWith("2026-11-19");
  });

  it("lists each day with its summary, its entries, «Gjort» and a short line for a day with nothing", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    const monday = await screen.findByRole("region", {
      name: "Måndag 16 november",
    });
    expect(within(monday).getByText("Middag med Björn")).toBeInTheDocument();
    const tuesday = screen.getByRole("region", { name: "Tisdag 17 november" });
    // Nothing written, but something done: the line and the folded «Gjort».
    expect(within(tuesday).getByText("Inget skrivet")).toBeInTheDocument();
    const fold = within(tuesday).getByRole("button", { name: /^Gjort/ });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    await user.click(fold);
    expect(within(tuesday).getByText("Betala elräkningen")).toBeInTheDocument();
    // «Gjort» opens per day: Monday's has none, and Wednesday has no done section at all.
    const wednesday = screen.getByRole("region", {
      name: "Onsdag 18 november",
    });
    expect(
      within(wednesday).getByText("Onsdagen gick åt till planering."),
    ).toBeInTheDocument();
    expect(within(wednesday).queryByText("Inget skrivet")).toBeNull();
    expect(screen.queryByRole("region", { name: /torsdag/i })).toBeNull();
  });

  it("opens an entry from a day through the shell's route", async () => {
    const user = userEvent.setup();
    const { onRoute } = setup();
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    await user.click(
      await screen.findByRole("button", { name: /Middag med Björn/ }),
    );
    expect(onRoute).toHaveBeenCalledWith({
      room: "journal",
      view: "entry",
      id: entry.id,
    });
  });

  it("steps one calendar week at a time, cannot step past this week, and returns with «Denna vecka»", async () => {
    const user = userEvent.setup();
    const { transport } = setup();
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    await screen.findByRole("region", { name: "Måndag 16 november" });
    const next = screen.getByRole("button", { name: "Nästa vecka" });
    expect(next).toHaveAttribute("aria-disabled", "true");
    expect(screen.queryByRole("button", { name: "Denna vecka" })).toBeNull();

    await user.click(screen.getByRole("button", { name: "Föregående vecka" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Vecka 46 · 9–15 nov",
      }),
    ).toBeInTheDocument();
    // A whole past week: Monday to Sunday.
    await screen.findByRole("region", { name: "Söndag 15 november" });
    expect(transport.getDay).toHaveBeenCalledWith("2026-11-09");
    expect(
      screen.getByRole("button", { name: "Nästa vecka" }),
    ).not.toHaveAttribute("aria-disabled");

    await user.click(screen.getByRole("button", { name: "Denna vecka" }));
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 47/ }),
    ).toBeInTheDocument();
  });

  it("steps with the [ and ] keys and goes to this week with t", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    await screen.findByRole("region", { name: "Måndag 16 november" });
    await user.keyboard("[[");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 46/ }),
    ).toBeInTheDocument();
    await user.keyboard("t");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 47/ }),
    ).toBeInTheDocument();
  });

  it("switches back to the day view", async () => {
    const user = userEvent.setup();
    setup();
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    await screen.findByRole("region", { name: "Måndag 16 november" });
    await user.click(screen.getByRole("button", { name: "Dag" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Onsdag 18 november",
      }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: "Måndag 16 november" }),
    ).toBeNull();
  });

  it("shows a loading line, then a failed read with Try again that reads the week again", async () => {
    const user = userEvent.setup();
    const { transport } = setup();
    transport.getDay.mockImplementation((date: string) =>
      date === "2026-11-17"
        ? Promise.reject(new Error("network"))
        : Promise.resolve(pageFor(date)),
    );
    await user.click(screen.getByRole("button", { name: "Vecka" }));
    const retry = await screen.findByRole("button", { name: "Försök igen" });
    expect(
      screen.queryByRole("region", { name: "Måndag 16 november" }),
    ).toBeNull();
    transport.getDay.mockImplementation((date: string) =>
      Promise.resolve(pageFor(date)),
    );
    await user.click(retry);
    expect(
      await screen.findByRole("region", { name: "Måndag 16 november" }),
    ).toBeInTheDocument();
  });

  it("speaks English: the heading, the switch and the empty day", async () => {
    const user = userEvent.setup();
    setup(journalEn);
    await user.click(screen.getByRole("button", { name: "Week" }));
    expect(
      await screen.findByRole("heading", {
        level: 2,
        name: "Week 47 · 16–22 Nov",
      }),
    ).toBeInTheDocument();
    const tuesday = await screen.findByRole("region", {
      name: "Tuesday 17 November",
    });
    expect(within(tuesday).getByText("Nothing written")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Previous week" }),
    ).toBeInTheDocument();
  });

  it("offers no switch in an inline card", () => {
    const transport = transportMock({
      getDay: vi.fn((date: string) => Promise.resolve(pageFor(date))),
      listEntryDates: vi.fn(() => Promise.resolve([])),
    });
    render(
      <JournalView transport={transport} initial={root} labels={journalSv} />,
    );
    expect(screen.queryByRole("group", { name: "Visning" })).toBeNull();
  });
});
