import { describe, expect, it } from "vitest";

import {
  dayText,
  nextOccurrenceDay,
  weekdayOf,
  type NextRule,
} from "@/features/work-app/tasks/repeat-next";

/*
 * The next occurrence of a repeat rule, mirroring RecurrenceRule.next_due_at in the backend (the expected days follow its
 * rules by hand). `today` stands for the day the Task is completed; Friday 20 November 2026 unless a case says otherwise.
 */

const DAY_MS = 86_400_000;
const day = (year: number, month: number, date: number) =>
  Math.round(Date.UTC(year, month - 1, date) / DAY_MS);
const FRIDAY = day(2026, 11, 20);

function next(
  rule: NextRule,
  options: { today?: number; due?: number | null } = {},
): string | null {
  const found = nextOccurrenceDay(
    rule,
    options.today ?? FRIDAY,
    options.due ?? null,
  );
  return found === null ? null : dayText(found);
}

describe("weekdayOf", () => {
  it("counts Monday as 0 like the rule's weekdays", () => {
    expect(weekdayOf(FRIDAY)).toBe(4);
    expect(weekdayOf(day(2026, 11, 22))).toBe(6);
    expect(weekdayOf(day(2026, 11, 23))).toBe(0);
    expect(weekdayOf(day(1969, 12, 31))).toBe(2);
  });
});

describe("the next occurrence of a daily or weekly rule", () => {
  it("adds the interval in days for a daily rule", () => {
    expect(next({ frequency: "daily", interval: 1 })).toBe("2026-11-21");
    expect(next({ frequency: "daily", interval: 3 })).toBe("2026-11-23");
  });

  it("is a whole number of weeks after completion when no weekday is chosen", () => {
    expect(next({ frequency: "weekly", interval: 1, weekdays: [] })).toBe(
      "2026-11-27",
    );
    expect(next({ frequency: "weekly", interval: 2 })).toBe("2026-12-04");
  });

  it("takes the first chosen weekday after today for a weekly rule", () => {
    expect(next({ frequency: "weekly", interval: 1, weekdays: [1] })).toBe(
      "2026-11-24",
    );
    expect(next({ frequency: "weekly", interval: 1, weekdays: [0, 3] })).toBe(
      "2026-11-23",
    );
    // The same weekday as today is a week ahead, never today.
    expect(next({ frequency: "weekly", interval: 1, weekdays: [4] })).toBe(
      "2026-11-27",
    );
  });

  it("stays in this week for every other week while a chosen weekday is ahead, else jumps two weeks", () => {
    expect(
      next({ frequency: "weekly", interval: 2, weekdays: [0, 4, 5] }),
    ).toBe("2026-11-21");
    expect(next({ frequency: "weekly", interval: 2, weekdays: [0, 3] })).toBe(
      "2026-11-30",
    );
    expect(next({ frequency: "weekly", interval: 2, weekdays: [4] })).toBe(
      "2026-12-04",
    );
  });
});

describe("the next occurrence of a monthly rule", () => {
  it("keeps the day the Task is due on, from the month it is due in", () => {
    expect(next({ frequency: "monthly" }, { due: day(2026, 11, 15) })).toBe(
      "2026-12-15",
    );
    expect(next({ frequency: "monthly" })).toBe("2026-12-20");
  });

  it("clamps day 31 to the end of a shorter month", () => {
    expect(next({ frequency: "monthly" }, { today: day(2026, 1, 31) })).toBe(
      "2026-02-28",
    );
    expect(next({ frequency: "monthly" }, { today: day(2028, 1, 31) })).toBe(
      "2028-02-29",
    );
  });

  it("steps past a long-overdue due date until the occurrence is after today", () => {
    expect(next({ frequency: "monthly" }, { due: day(2026, 8, 10) })).toBe(
      "2026-12-10",
    );
    expect(next({ frequency: "monthly" }, { due: day(2026, 10, 31) })).toBe(
      "2026-11-30",
    );
  });

  it("wraps the year and counts the interval in months", () => {
    expect(next({ frequency: "monthly" }, { today: day(2026, 12, 20) })).toBe(
      "2027-01-20",
    );
    expect(
      next({ frequency: "monthly", interval: 3 }, { due: day(2026, 11, 15) }),
    ).toBe("2027-02-15");
  });

  it("uses a day of the month of its own", () => {
    expect(next({ frequency: "monthly", day_of_month: 5 })).toBe("2026-12-05");
    expect(next({ frequency: "monthly", day_of_month: 31 })).toBe("2026-12-31");
  });

  it("falls on the last Monday to Friday of the month", () => {
    // December 2026 ends on a Thursday, February 2026 on a Saturday, May 2027 on a Monday.
    expect(next({ frequency: "monthly", last_weekday: true })).toBe(
      "2026-12-31",
    );
    expect(
      next(
        { frequency: "monthly", last_weekday: true },
        { today: day(2026, 1, 15) },
      ),
    ).toBe("2026-02-27");
    expect(
      next(
        { frequency: "monthly", last_weekday: true },
        { today: day(2027, 4, 10) },
      ),
    ).toBe("2027-05-31");
    // A Sunday end falls back two days.
    expect(
      next(
        { frequency: "monthly", last_weekday: true },
        { today: day(2026, 12, 10) },
      ),
    ).toBe("2027-01-29");
  });
});

describe("the next occurrence of a yearly rule", () => {
  it("is the same date next year, or the 28th when 29 February does not exist", () => {
    expect(next({ frequency: "yearly" })).toBe("2027-11-20");
    expect(next({ frequency: "yearly" }, { today: day(2028, 2, 29) })).toBe(
      "2029-02-28",
    );
    expect(
      next({ frequency: "yearly", interval: 4 }, { today: day(2028, 2, 29) }),
    ).toBe("2032-02-29");
  });
});

describe("the end of a rule", () => {
  it("gives nothing when the next occurrence is after the end date", () => {
    expect(next({ frequency: "daily", until: "2026-11-20" })).toBeNull();
    expect(next({ frequency: "daily", until: "2026-11-21" })).toBe(
      "2026-11-21",
    );
  });

  it("gives nothing for an interval the server would refuse", () => {
    expect(next({ frequency: "daily", interval: 0 })).toBeNull();
    expect(next({ frequency: "daily", interval: 13 })).toBeNull();
  });
});
