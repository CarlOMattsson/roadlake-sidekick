import { describe, expect, it } from "vitest";

import {
  formatDayHeading,
  formatShortDateWithYear,
  relativeDay,
} from "@/features/journal-app/dates";

// 2026-11-03 is a Tuesday. 2025-11-03 was a Monday.
const TODAY = "2026-11-03";

describe("formatDayHeading", () => {
  it("shows the weekday, day and full month in Swedish, without the year in the current year", () => {
    expect(formatDayHeading(TODAY, "sv-SE", TODAY)).toBe("Tisdag 3 november");
  });

  it("shows the weekday, day and full month in English", () => {
    expect(formatDayHeading(TODAY, "en-GB", TODAY)).toBe("Tuesday 3 November");
  });

  it("adds the year only when it is not the year of today", () => {
    expect(formatDayHeading("2025-11-03", "sv-SE", TODAY)).toBe(
      "Måndag 3 november 2025",
    );
  });

  it("gives the short weekday for a narrow title row, in both languages", () => {
    expect(formatDayHeading("2026-11-04", "en-GB", TODAY, "short")).toBe(
      "Wed 4 November",
    );
    expect(formatDayHeading("2026-11-04", "sv-SE", TODAY, "short")).toBe(
      "Ons 4 november",
    );
    expect(formatDayHeading("2025-11-03", "en-GB", TODAY, "short")).toBe(
      "Mon 3 November 2025",
    );
  });

  it("returns a malformed date unchanged", () => {
    expect(formatDayHeading("not a date", "sv-SE", TODAY)).toBe("not a date");
  });
});

describe("formatShortDateWithYear", () => {
  it("leaves out the year in the current year and adds it otherwise", () => {
    expect(formatShortDateWithYear("2026-10-24", "sv-SE", TODAY)).toBe(
      "24 okt",
    );
    expect(formatShortDateWithYear("2025-12-31", "en-GB", TODAY)).toBe(
      "31 Dec 2025",
    );
  });

  it("gives every English month three letters, September too", () => {
    expect(formatShortDateWithYear("2026-09-14", "en-GB", TODAY)).toBe(
      "14 Sep",
    );
    expect(formatShortDateWithYear("2025-09-14", "en-GB", TODAY)).toBe(
      "14 Sep 2025",
    );
    expect(formatShortDateWithYear("2026-09-14", "sv-SE", TODAY)).toBe(
      "14 sep",
    );
  });
});

describe("relativeDay", () => {
  it("names today and yesterday, and nothing else", () => {
    expect(relativeDay(TODAY, TODAY)).toBe("today");
    expect(relativeDay("2026-11-02", TODAY)).toBe("yesterday");
    expect(relativeDay("2026-11-01", TODAY)).toBeUndefined();
    expect(relativeDay("2026-11-04", TODAY)).toBeUndefined();
  });

  it("finds yesterday across a month boundary", () => {
    expect(relativeDay("2026-10-31", "2026-11-01")).toBe("yesterday");
  });
});
