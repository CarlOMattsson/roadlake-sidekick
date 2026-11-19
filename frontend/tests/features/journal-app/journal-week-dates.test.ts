import { describe, expect, it } from "vitest";

import {
  isoWeekNumber,
  weekDates,
  weekStart,
} from "@/features/journal-app/dates";
import { weekHeadingRange } from "@/features/journal-app/week-frame";

describe("weekStart", () => {
  it("is the Monday of the calendar week, for every day of it", () => {
    // 2026-11-16 is a Monday, 2026-11-22 a Sunday.
    for (const date of weekDates("2026-11-18")) {
      expect(weekStart(date)).toBe("2026-11-16");
    }
  });

  it("goes back over a month boundary", () => {
    // 2026-11-01 is a Sunday: its week began on Monday 26 October.
    expect(weekStart("2026-11-01")).toBe("2026-10-26");
  });

  it("goes back over a year boundary", () => {
    // 2027-01-01 is a Friday: its week began on Monday 28 December.
    expect(weekStart("2027-01-01")).toBe("2026-12-28");
  });

  it("returns a malformed date unchanged", () => {
    expect(weekStart("not a date")).toBe("not a date");
  });
});

describe("weekDates", () => {
  it("lists Monday to Sunday", () => {
    expect(weekDates("2026-11-18")).toEqual([
      "2026-11-16",
      "2026-11-17",
      "2026-11-18",
      "2026-11-19",
      "2026-11-20",
      "2026-11-21",
      "2026-11-22",
    ]);
  });

  it("runs over a year boundary", () => {
    expect(weekDates("2026-12-30")).toEqual([
      "2026-12-28",
      "2026-12-29",
      "2026-12-30",
      "2026-12-31",
      "2027-01-01",
      "2027-01-02",
      "2027-01-03",
    ]);
  });

  it("is empty for a malformed date", () => {
    expect(weekDates("2026-13")).toEqual([]);
  });
});

describe("isoWeekNumber", () => {
  it("numbers the weeks of 2026 by the ISO rule", () => {
    expect(isoWeekNumber("2026-11-16")).toBe(47);
    expect(isoWeekNumber("2026-11-22")).toBe(47);
    expect(isoWeekNumber("2026-11-23")).toBe(48);
    expect(isoWeekNumber("2026-01-05")).toBe(2);
  });

  it("puts the days before the first Thursday in the last week of the year before", () => {
    // 2027-01-01 is a Friday, so it still belongs to week 53 of 2026.
    expect(isoWeekNumber("2027-01-01")).toBe(53);
    expect(isoWeekNumber("2027-01-04")).toBe(1);
  });

  it("puts the first days of January in week 1 when the week holds a Thursday of the new year", () => {
    // 2025-01-01 is a Wednesday, in the week of Monday 30 December 2024.
    expect(isoWeekNumber("2025-01-01")).toBe(1);
    expect(isoWeekNumber("2024-12-30")).toBe(1);
    expect(isoWeekNumber("2024-12-29")).toBe(52);
  });

  it("is 0 for a malformed date", () => {
    expect(isoWeekNumber("nope")).toBe(0);
  });
});

describe("weekHeadingRange", () => {
  const today = "2026-11-18";

  it("gives one month as '16–22 nov' and two months with both names", () => {
    expect(weekHeadingRange(weekDates("2026-11-18"), "sv-SE", today)).toBe(
      "16–22 nov",
    );
    expect(weekHeadingRange(weekDates("2026-11-01"), "sv-SE", today)).toBe(
      "26 okt–1 nov",
    );
  });

  it("adds the year only for a week outside the year of today, and both years across a year boundary", () => {
    expect(weekHeadingRange(weekDates("2025-11-18"), "sv-SE", today)).toBe(
      "17–23 nov 2025",
    );
    expect(weekHeadingRange(weekDates("2027-01-01"), "en-GB", today)).toBe(
      "28 Dec 2026–3 Jan 2027",
    );
  });
});
