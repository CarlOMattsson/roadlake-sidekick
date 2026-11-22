// The week view's head and its empty days: runs of empty days as one quiet line, the head's arrows before the name,
// ← and → stepping a week, and + only where the room can write. A simulated host: the transport is a mock, so this
// is not a proof in the real Claude or Android host.
import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type {
  JournalDay,
  JournalFrame,
} from "@/features/journal-app/transport";
import { WeekFrame } from "@/features/journal-app/week-frame";
import {
  isEmptyDay,
  weekGapText,
  weekSegments,
} from "@/features/journal-app/week-gaps";
import {
  emptyDay,
  entry,
  transportMock,
} from "@tests/helpers/journal-app-fixtures";

// Wednesday 18 November 2026: its week is Monday 16 to Sunday 22 November, week 47.
const TODAY = "2026-11-18";

function written(date: string): JournalDay {
  return { ...emptyDay(date), entries: [{ ...entry, journal_date: date }] };
}

describe("weekSegments", () => {
  const days = (...kinds: ("e" | "w")[]) =>
    kinds.map((kind, index) => {
      const date = `2026-11-${String(16 + index).padStart(2, "0")}`;
      return kind === "w" ? written(date) : emptyDay(date);
    });

  it("folds each run of empty days into one gap and keeps the written days", () => {
    const segments = weekSegments(days("e", "e", "e", "w", "e", "w"));
    expect(segments.map((s) => s.kind)).toEqual(["gap", "day", "gap", "day"]);
    expect(segments[0]).toEqual({
      kind: "gap",
      dates: ["2026-11-16", "2026-11-17", "2026-11-18"],
    });
    expect(segments[2]).toEqual({ kind: "gap", dates: ["2026-11-20"] });
  });

  it("makes one gap of a week with nothing, and none of a week with something every day", () => {
    expect(weekSegments(days("e", "e", "e", "e", "e", "e", "e"))).toHaveLength(
      1,
    );
    expect(weekSegments(days("w", "w", "w")).map((s) => s.kind)).toEqual([
      "day",
      "day",
      "day",
    ]);
  });

  it("does not fold a day that only has something done", () => {
    const done = {
      ...emptyDay("2026-11-17"),
      done: {
        tasks: [],
        steps: [],
        purchases: [],
        counts: { tasks: 1, steps: 0, purchases: 0 },
        truncated: false,
      },
    };
    expect(isEmptyDay(done)).toBe(false);
    expect(isEmptyDay(emptyDay("2026-11-17"))).toBe(true);
  });
});

describe("weekGapText", () => {
  it("names a run, one day and a whole week, in Swedish and in English", () => {
    const run = ["2026-11-16", "2026-11-17", "2026-11-18"];
    expect(weekGapText(run, journalSv, undefined)).toBe(
      "Inget skrivet mån–ons",
    );
    expect(weekGapText(run, journalEn, undefined)).toBe(
      "Nothing written Mon–Wed",
    );
    expect(weekGapText(["2026-11-19"], journalSv, undefined)).toBe(
      "Inget skrivet tors",
    );
    expect(weekGapText(["2026-11-19"], journalEn, undefined)).toBe(
      "Nothing written Thu",
    );
    expect(weekGapText(run, journalSv, 44)).toBe("Inget skrivet vecka 44");
    expect(weekGapText(run, journalEn, 44)).toBe("Nothing written week 44");
  });
});

/** The week view on its own, in a mock host, with the week held in state as the room does. */
function Harness({
  labels,
  onShowDay,
  onAdd,
  pages,
}: {
  labels: typeof journalSv;
  onShowDay: (date?: string) => void;
  onAdd?: () => void;
  pages: (date: string) => JournalDay;
}) {
  const [start, setStart] = useState("2026-11-16");
  const [transport] = useState(() =>
    transportMock({
      getDay: vi.fn((date: string) => Promise.resolve(pages(date))),
      listEntryDates: vi.fn(() => Promise.resolve([])),
    }),
  );
  const frame: Extract<JournalFrame, { kind: "day" }> = {
    kind: "day",
    page: pages(TODAY),
  };
  return (
    <WeekFrame
      frame={frame}
      start={start}
      onStart={setStart}
      onShowDay={onShowDay}
      onAdd={onAdd}
      onOpen={vi.fn()}
      transport={transport}
      labels={labels}
      moves={0}
    />
  );
}

describe("week view head and gaps", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date(`${TODAY}T12:00:00Z`));
  });
  afterEach(() => vi.useRealTimers());

  const monday = (date: string) =>
    date === "2026-11-16" ? written(date) : emptyDay(date);

  it("folds the empty days after a written one into one line whose link opens the first of them", async () => {
    const user = userEvent.setup();
    const onShowDay = vi.fn();
    render(<Harness labels={journalSv} onShowDay={onShowDay} pages={monday} />);
    await screen.findByRole("region", { name: "Måndag 16 november" });
    // Tuesday and Wednesday (today) are empty: one line, no day headings of their own.
    expect(screen.getByText("Inget skrivet tis–ons")).toBeInTheDocument();
    expect(screen.queryByRole("region", { name: /tisdag/i })).toBeNull();
    await user.click(screen.getByRole("button", { name: /Skriv för en dag/ }));
    expect(onShowDay).toHaveBeenCalledWith("2026-11-17");
  });

  it("makes a week with nothing one line, in English too", async () => {
    const user = userEvent.setup();
    const onShowDay = vi.fn();
    render(
      <Harness
        labels={journalEn}
        onShowDay={onShowDay}
        pages={(date) => emptyDay(date)}
      />,
    );
    expect(
      await screen.findByText("Nothing written week 47"),
    ).toBeInTheDocument();
    expect(screen.queryAllByRole("region")).toHaveLength(0);
    await user.click(screen.getByRole("button", { name: /Write for a day/ }));
    expect(onShowDay).toHaveBeenCalledWith("2026-11-16");
  });

  it("puts ‹ › together before the week's name, whatever the name says, and keeps «Denna vecka» out of the head", async () => {
    const user = userEvent.setup();
    render(<Harness labels={journalSv} onShowDay={vi.fn()} pages={monday} />);
    await screen.findByRole("region", { name: "Måndag 16 november" });
    const arrowsBefore = () => {
      const previous = screen.getByRole("button", { name: "Föregående vecka" });
      const next = screen.getByRole("button", { name: "Nästa vecka" });
      const heading = screen.getByRole("heading", { level: 2 });
      const group = previous.parentElement;
      expect(group).toBe(next.parentElement);
      expect(previous.nextElementSibling).toBe(next);
      // The group is the head's first child and the name follows it.
      expect(group?.nextElementSibling).toContainElement(heading);
      expect(group?.previousElementSibling).toBeNull();
      return group?.parentElement;
    };
    const head = arrowsBefore();
    await user.click(screen.getByRole("button", { name: "Föregående vecka" }));
    await screen.findByRole("heading", { level: 2, name: /^Vecka 46/ });
    // «Denna vecka» appears in the room head, not between the arrows and the name.
    const thisWeek = screen.getByRole("button", { name: "Denna vecka" });
    expect(head).not.toContainElement(thisWeek);
    expect(arrowsBefore()).toBe(head);
  });

  it("steps a week with ← and →, and goes to this week with t", async () => {
    const user = userEvent.setup();
    render(<Harness labels={journalSv} onShowDay={vi.fn()} pages={monday} />);
    await screen.findByRole("region", { name: "Måndag 16 november" });
    await user.keyboard("{ArrowLeft}");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 46/ }),
    ).toBeInTheDocument();
    await user.keyboard("{ArrowLeft}");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 45/ }),
    ).toBeInTheDocument();
    await user.keyboard("{ArrowRight}");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 46/ }),
    ).toBeInTheDocument();
    await user.keyboard("t");
    expect(
      await screen.findByRole("heading", { level: 2, name: /^Vecka 47/ }),
    ).toBeInTheDocument();
  });

  it("draws + only with onAdd, and + calls it", async () => {
    const user = userEvent.setup();
    const { unmount } = render(
      <Harness labels={journalSv} onShowDay={vi.fn()} pages={monday} />,
    );
    await screen.findByRole("region", { name: "Måndag 16 november" });
    expect(
      screen.queryByRole("button", { name: journalSv.addEntry }),
    ).toBeNull();
    unmount();
    const onAdd = vi.fn();
    render(
      <Harness
        labels={journalSv}
        onShowDay={vi.fn()}
        onAdd={onAdd}
        pages={monday}
      />,
    );
    const week = await screen.findByRole("region", {
      name: "Måndag 16 november",
    });
    expect(week).toBeInTheDocument();
    const add = screen.getByRole("button", { name: journalSv.addEntry });
    expect(add).toHaveClass("sk-room-head__add");
    await user.click(add);
    expect(onAdd).toHaveBeenCalledTimes(1);
    expect(
      within(document.body).getAllByRole("button", {
        name: journalSv.addEntry,
      }),
    ).toHaveLength(1);
  });
});
