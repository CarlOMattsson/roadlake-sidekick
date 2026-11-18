import { describe, expect, it } from "vitest";

import {
  dueClockText,
  moveDueToDay,
  ownerClockTime,
  ownerDueAt,
  ownerEndOfDay,
} from "@/features/mcp-apps/ui/due";

// Stockholm reference points: CET is UTC+1 in winter and CEST UTC+2 in summer; 2026-03-29 is the spring switch and
// 2026-10-25 the autumn switch.
describe("the clock time of a due instant", () => {
  it("reads the owner-zone time, winter and summer", () => {
    expect(ownerClockTime("2026-11-18T16:30:00.000Z")).toBe("17:30");
    expect(ownerClockTime("2026-07-01T15:30:00Z")).toBe("17:30");
    expect(ownerClockTime("2026-11-18T08:05:00+01:00")).toBe("08:05");
  });

  it("is none for 23:59, a bare date, a missing or unreadable value", () => {
    expect(ownerClockTime("2026-11-18T22:59:00.000Z")).toBeNull();
    expect(ownerClockTime("2026-07-01T21:59:00.000Z")).toBeNull();
    expect(ownerClockTime("2026-11-18")).toBeNull();
    expect(ownerClockTime(null)).toBeNull();
    expect(ownerClockTime(undefined)).toBeNull();
    expect(ownerClockTime("not a date")).toBeNull();
  });

  it("reads midnight as 00:00, not 24:00", () => {
    expect(ownerClockTime("2026-11-17T23:00:00.000Z")).toBe("00:00");
  });
});

describe("a due instant from a day and a time", () => {
  it("gives the owner-zone time, and 23:59 without a time", () => {
    expect(ownerDueAt("2026-11-18", "17:30")).toBe("2026-11-18T16:30:00.000Z");
    expect(ownerDueAt("2026-07-01", "17:30")).toBe("2026-07-01T15:30:00.000Z");
    expect(ownerDueAt("2026-11-18", null)).toBe(ownerEndOfDay("2026-11-18"));
    expect(ownerDueAt("2026-11-18", "")).toBe(ownerEndOfDay("2026-11-18"));
    expect(ownerDueAt("2026-11-18", "25:00")).toBe(ownerEndOfDay("2026-11-18"));
  });
});

describe("moving a due date to another day", () => {
  it("keeps the clock time", () => {
    expect(moveDueToDay("2026-11-18T16:30:00.000Z", "2026-11-19")).toBe(
      "2026-11-19T16:30:00.000Z",
    );
  });

  it("keeps the clock time across the spring and autumn switches", () => {
    // 17:30 in winter (16:30Z) moved past the spring switch is 17:30 in summer (15:30Z).
    expect(moveDueToDay("2026-03-27T16:30:00.000Z", "2026-03-30")).toBe(
      "2026-03-30T15:30:00.000Z",
    );
    expect(moveDueToDay("2026-10-20T15:30:00.000Z", "2026-10-27")).toBe(
      "2026-10-27T16:30:00.000Z",
    );
    expect(moveDueToDay("2026-03-27T16:30:00.000Z", "2026-03-29")).toBe(
      "2026-03-29T15:30:00.000Z",
    );
  });

  it("gives 23:59 for a bare date, a missing due and a 23:59 due", () => {
    expect(moveDueToDay("2026-11-18T22:59:00.000Z", "2026-11-19")).toBe(
      "2026-11-19T22:59:00.000Z",
    );
    expect(moveDueToDay(null, "2026-11-19")).toBe("2026-11-19T22:59:00.000Z");
    expect(moveDueToDay("2026-11-18", "2026-11-19")).toBe(
      "2026-11-19T22:59:00.000Z",
    );
  });

  it("takes the day of a shortcut instant", () => {
    expect(
      moveDueToDay("2026-11-18T16:30:00.000Z", "2026-11-19T22:59:00.000Z"),
    ).toBe("2026-11-19T16:30:00.000Z");
  });

  it("rejects an unreadable day", () => {
    expect(() => moveDueToDay(null, "tomorrow")).toThrow(RangeError);
  });
});

describe("the clock time as text", () => {
  it("reads kl 17:30 in Swedish and 5:30 pm in English", () => {
    const due = "2026-11-18T16:30:00.000Z";
    expect(dueClockText(due, "sv-SE")).toBe("kl 17:30");
    expect(dueClockText(due, "en-GB")).toBe("5:30 pm");
    expect(dueClockText("2026-11-18T11:05:00.000Z", "en-GB")).toBe("12:05 pm");
    expect(dueClockText("2026-11-17T23:05:00.000Z", "en-GB")).toBe("12:05 am");
  });

  it("is empty for a bare date", () => {
    expect(dueClockText("2026-11-18T22:59:00.000Z", "sv-SE")).toBe("");
    expect(dueClockText(null, "en-GB")).toBe("");
  });
});
