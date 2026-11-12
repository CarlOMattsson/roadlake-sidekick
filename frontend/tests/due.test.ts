import { afterEach, describe, expect, it } from "vitest";

import { triageDueAt } from "../src/features/work-app/shared/work-items";

import {
  relativeDue,
  ownerDayPlus,
  ownerDaysToNextMonday,
  ownerEndOfDay,
  workDate,
  type DueLocale,
  type DueTone,
} from "../src/features/mcp-apps/ui/due";

// Stockholm reference points (verified with Intl, Europe/Stockholm):
// - 2026-10-25 is the autumn DST switch (03:00 CEST -> 02:00 CET).
// - 2026-03-29 is the spring DST switch (02:00 CET -> 03:00 CEST).
// - 2026-11-03 00:00 CET is 2026-11-02T23:00:00Z.

describe("relativeDue midnight and DST in Europe/Stockholm", () => {
  it.each<[string, string, string, string]>([
    // [label, now (UTC instant), due (YYYY-MM-DD), expected text]
    [
      "23:59:59 on the day is still today",
      "2026-11-02T22:59:59Z",
      "2026-11-02",
      "Idag",
    ],
    [
      "00:00 next day makes yesterday overdue",
      "2026-11-02T23:00:00Z",
      "2026-11-02",
      "1 dag försenad",
    ],
    [
      "00:00 next day makes today",
      "2026-11-02T23:00:00Z",
      "2026-11-03",
      "Idag",
    ],
    [
      "autumn DST, before the switch",
      "2026-10-24T22:30:00Z",
      "2026-10-25",
      "Idag",
    ],
    [
      "autumn DST, after the switch",
      "2026-10-25T01:30:00Z",
      "2026-10-25",
      "Idag",
    ],
    [
      "spring DST, before the switch",
      "2026-03-28T23:30:00Z",
      "2026-03-29",
      "Idag",
    ],
    [
      "spring DST, after the switch, yesterday",
      "2026-03-29T22:30:00Z",
      "2026-03-29",
      "1 dag försenad",
    ],
    [
      "spring DST, after the switch, today",
      "2026-03-29T22:30:00Z",
      "2026-03-30",
      "Idag",
    ],
  ])("%s", (_label, now, due, expected) => {
    const result = relativeDue(due, new Date(now), "sv");
    expect(result.text).toBe(expected);
  });

  it.each<[string, string, string, DueTone]>([
    ["midnight, today", "2026-11-02T22:59:59Z", "2026-11-02", "today"],
    ["midnight, overdue", "2026-11-02T23:00:00Z", "2026-11-02", "overdue"],
    ["autumn DST, today", "2026-10-25T01:30:00Z", "2026-10-25", "today"],
    ["spring DST, overdue", "2026-03-29T22:30:00Z", "2026-03-29", "overdue"],
  ])("tone: %s", (_label, now, due, tone) => {
    expect(relativeDue(due, new Date(now), "sv").tone).toBe(tone);
  });
});

describe("relativeDue labels and tones (sv)", () => {
  const now = new Date("2026-10-25T10:00:00Z"); // Sunday 2026-10-25, 11:00 CET

  it.each<[string, string | null | undefined, string, DueTone]>([
    ["overdue 2 days", "2026-10-23", "2 dagar försenad", "overdue"],
    ["today", "2026-10-25", "Idag", "today"],
    ["tomorrow", "2026-10-26", "Imorgon", "soon"],
    ["Friday within a week", "2026-10-30", "fre 30 okt", "soon"],
    ["6 days ahead is still soon", "2026-10-31", "lör 31 okt", "soon"],
    ["7 days ahead is later", "2026-11-01", "sön 1 nov", "later"],
    ["12 days ahead shows the date only", "2026-11-06", "6 nov", "later"],
  ])("%s", (_label, due, text, tone) => {
    expect(relativeDue(due, now, "sv")).toEqual({ text, tone });
  });
});

describe("relativeDue labels and tones (en)", () => {
  const now = new Date("2026-10-25T10:00:00Z");

  it.each<[string, string | null | undefined, string, DueTone]>([
    ["overdue 2 days", "2026-10-23", "2 days overdue", "overdue"],
    ["today", "2026-10-25", "Today", "today"],
    ["tomorrow", "2026-10-26", "Tomorrow", "soon"],
    ["Friday within a week", "2026-10-30", "Fri 30 Oct", "soon"],
    ["later date shows the date only", "2026-11-06", "6 Nov", "later"],
  ])("%s", (_label, due, text, tone) => {
    expect(relativeDue(due, now, "en")).toEqual({ text, tone });
  });
});

describe("relativeDue ISO timestamps are converted to Stockholm time", () => {
  it.each<[string, string, string, string, DueTone]>([
    // [label, now (UTC instant), due (ISO datetime), expected text, tone]
    [
      "winter 23:30Z is the next day in Stockholm",
      "2026-11-03T10:00:00Z",
      "2026-11-03T23:30:00Z",
      "Imorgon",
      "soon",
    ],
    [
      "winter 22:59:59Z is still today in Stockholm",
      "2026-11-03T10:00:00Z",
      "2026-11-03T22:59:59Z",
      "Idag",
      "today",
    ],
    [
      "winter offset +01:00 past midnight is the next day",
      "2026-11-03T10:00:00Z",
      "2026-11-04T00:30:00+01:00",
      "Imorgon",
      "soon",
    ],
    [
      "offset -05:00 converts to the next day in Stockholm",
      "2026-11-03T10:00:00Z",
      "2026-11-03T20:00:00-05:00",
      "Imorgon",
      "soon",
    ],
    [
      "summer 21:59Z is still today (23:59 CEST)",
      "2026-07-15T12:00:00Z",
      "2026-07-15T21:59:00Z",
      "Idag",
      "today",
    ],
    [
      "summer 22:00Z is midnight CEST, the next day",
      "2026-07-15T12:00:00Z",
      "2026-07-15T22:00:00Z",
      "Imorgon",
      "soon",
    ],
    [
      "summer offset +02:00 just after midnight is the next day",
      "2026-07-15T12:00:00Z",
      "2026-07-16T00:30:00+02:00",
      "Imorgon",
      "soon",
    ],
    [
      "summer offset timestamp on the same Stockholm day is today",
      "2026-07-16T12:00:00Z",
      "2026-07-16T00:30:00+02:00",
      "Idag",
      "today",
    ],
  ])("%s", (_label, now, due, text, tone) => {
    expect(relativeDue(due, new Date(now), "sv")).toEqual({ text, tone });
  });

  it("accepts a timestamp with fractional seconds", () => {
    expect(
      relativeDue(
        "2026-11-03T23:30:00.250Z",
        new Date("2026-11-03T10:00:00Z"),
        "en",
      ),
    ).toEqual({ text: "Tomorrow", tone: "soon" });
  });
});

// The overdue count is the number of Stockholm calendar days from the due day to today, so it
// grows at Stockholm midnight, not at UTC midnight. Stockholm is CET (UTC+1) from 2026-10-25 01:00Z.
describe("relativeDue overdue day count across Stockholm midnight", () => {
  it.each<[string, string, string, string]>([
    // [label, now (UTC instant), due (YYYY-MM-DD or ISO datetime), expected text]
    [
      "26 Oct 23:59:59 CET: due 21 Oct is 5 d overdue",
      "2026-10-26T22:59:59Z",
      "2026-10-21",
      "5 dagar försenad",
    ],
    [
      "27 Oct 00:00 CET: due 21 Oct is 6 d overdue",
      "2026-10-26T23:00:00Z",
      "2026-10-21",
      "6 dagar försenad",
    ],
    [
      "27 Oct 00:30 CET (still 26 Oct in UTC): due 21 Oct is 6 d overdue",
      "2026-10-26T23:30:00Z",
      "2026-10-21",
      "6 dagar försenad",
    ],
    [
      "date-only due is never shifted: 21 Oct at 00:30 CET is still 21 Oct",
      "2026-10-26T23:30:00Z",
      "2026-10-21",
      "6 dagar försenad",
    ],
    [
      "ISO datetime 21 Oct 23:59 CEST is the 21st, so 6 d overdue",
      "2026-10-27T10:00:00Z",
      "2026-10-21T21:59:00Z",
      "6 dagar försenad",
    ],
    [
      "ISO datetime 22 Oct 00:00 CEST is the 22nd, so 5 d overdue",
      "2026-10-27T10:00:00Z",
      "2026-10-21T22:00:00Z",
      "5 dagar försenad",
    ],
  ])("%s", (_label, now, due, expected) => {
    expect(relativeDue(due, new Date(now), "sv").text).toBe(expected);
  });

  it("counts the same overdue days in English", () => {
    expect(
      relativeDue("2026-10-21", new Date("2026-10-26T23:30:00Z"), "en"),
    ).toEqual({ text: "6 days overdue", tone: "overdue" });
  });
});

describe("relativeDue missing or invalid input", () => {
  const now = new Date("2026-10-25T10:00:00Z");

  it.each<[string, string | null | undefined]>([
    ["null", null],
    ["undefined", undefined],
    ["empty string", ""],
    ["impossible day 2026-02-30", "2026-02-30"],
    ["impossible month 2026-13-01", "2026-13-01"],
    ["timestamp without offset", "2026-10-25T09:00:00"],
    ["timestamp with impossible hour", "2026-10-25T25:00:00Z"],
    ["timestamp with impossible offset", "2026-10-25T09:00:00+24:00"],
    ["timestamp with impossible day", "2026-02-30T09:00:00Z"],
    ["timestamp with space instead of T", "2026-10-25 09:00:00Z"],
    ["free text", "imorgon"],
  ])("%s gives no label", (_label, due) => {
    const locales: DueLocale[] = ["sv", "en"];
    for (const locale of locales) {
      expect(relativeDue(due, now, locale)).toEqual({ text: "", tone: "none" });
    }
  });

  it("gives no label for an invalid now", () => {
    expect(relativeDue("2026-10-25", new Date("not a date"), "sv")).toEqual({
      text: "",
      tone: "none",
    });
  });
});

// The shared Work date formatter. Reference: now is Sunday 2026-10-25 11:00 CET.
describe("workDate in the Work app", () => {
  const now = new Date("2026-10-25T10:00:00Z");

  it.each<[string, string | null | undefined, string]>([
    ["today", "2026-10-25", "Idag"],
    ["tomorrow", "2026-10-26", "Imorgon"],
    ["yesterday", "2026-10-24", "Igår"],
    ["two days back shows the weekday", "2026-10-23", "Fre 23 okt"],
    ["within a week shows the weekday", "2026-10-30", "Fre 30 okt"],
    ["seven days ahead shows the weekday", "2026-11-01", "Sön 1 nov"],
    ["beyond a week shows the date only", "2026-11-06", "6 nov"],
    ["another year shows the year", "2027-01-05", "5 jan 2027"],
    [
      "a timestamp reads its Stockholm day",
      "2026-10-26T23:30:00Z",
      "Tis 27 okt",
    ],
    ["microseconds are read as well", "2026-10-26T10:00:00.123456Z", "Imorgon"],
    ["missing value gives an empty label", null, ""],
    ["impossible day gives an empty label", "2026-02-30", ""],
  ])("sv start: %s", (_label, value, text) => {
    expect(workDate(value, now, "sv-SE")).toBe(text);
  });

  it.each<[string, string | null | undefined, string]>([
    ["today in a sentence", "2026-10-25", "idag"],
    ["tomorrow in a sentence", "2026-10-26", "imorgon"],
    ["weekday in a sentence", "2026-10-30", "fre 30 okt"],
    ["date only in a sentence", "2026-11-06", "6 nov"],
  ])("sv inline: %s", (_label, value, text) => {
    expect(workDate(value, now, "sv-SE", { inline: true })).toBe(text);
  });

  it("relative false names the weekday and date, never idag or imorgon", () => {
    expect(workDate("2026-10-25", now, "sv-SE", { relative: false })).toBe(
      "Sön 25 okt",
    );
    expect(
      workDate("2026-10-26", now, "sv-SE", { inline: true, relative: false }),
    ).toBe("mån 26 okt");
    expect(
      workDate("2026-10-26", now, "en-GB", { inline: true, relative: false }),
    ).toBe("Mon 26 Oct");
  });

  it("English reads the same rules; only the relative words are in lower case inline", () => {
    expect(workDate("2026-10-25", now, "en-GB")).toBe("Today");
    expect(workDate("2026-10-26", now, "en-GB")).toBe("Tomorrow");
    expect(workDate("2026-10-24", now, "en-GB")).toBe("Yesterday");
    expect(workDate("2026-10-30", now, "en-GB")).toBe("Fri 30 Oct");
    expect(workDate("2026-11-06", now, "en-GB")).toBe("6 Nov");
    expect(workDate("2027-01-05", now, "en-GB")).toBe("5 Jan 2027");
    expect(workDate("2026-10-26", now, "en-GB", { inline: true })).toBe(
      "tomorrow",
    );
    expect(workDate("2026-10-30", now, "en-GB", { inline: true })).toBe(
      "Fri 30 Oct",
    );
  });
});

describe("ownerEndOfDay: 23:59 on the Stockholm day, whatever the browser's zone", () => {
  const original = process.env.TZ;
  afterEach(() => {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  });

  it.each<[string, string]>([
    ["2026-01-15", "2026-01-15T22:59:00.000Z"],
    ["2026-07-15", "2026-07-15T21:59:00.000Z"],
    // The day before and the day of the spring switch (29 Mar), and the day before and of the autumn switch (25 Oct).
    ["2026-03-28", "2026-03-28T22:59:00.000Z"],
    ["2026-03-29", "2026-03-29T21:59:00.000Z"],
    ["2026-10-24", "2026-10-24T21:59:00.000Z"],
    ["2026-10-25", "2026-10-25T22:59:00.000Z"],
  ])("%s is %s", (day, iso) => {
    expect(ownerEndOfDay(day)).toBe(iso);
  });

  it.each(["America/New_York", "Asia/Tokyo", "Pacific/Auckland", "UTC"])(
    "gives the same instant in the zone %s as in Stockholm",
    (zone) => {
      process.env.TZ = zone;
      expect(ownerEndOfDay("2026-01-15")).toBe("2026-01-15T22:59:00.000Z");
      expect(ownerEndOfDay("2026-07-15")).toBe("2026-07-15T21:59:00.000Z");
      // The picked day comes back as the same day when it is read in Stockholm, which a local 23:59 in UTC-5 did not.
      const back = new Intl.DateTimeFormat("en-CA", {
        timeZone: "Europe/Stockholm",
      }).format(new Date(ownerEndOfDay("2026-01-15")));
      expect(back).toBe("2026-01-15");
    },
  );
});

describe("Stockholm day arithmetic and triage due dates, whatever the browser's zone", () => {
  const original = process.env.TZ;
  afterEach(() => {
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  });
  const ZONES = ["America/New_York", "Asia/Tokyo", "Pacific/Auckland", "UTC"];

  // [label, instant (UTC), weekday in Stockholm, today, tomorrow, next Monday, days to next Monday], all as
  // Stockholm calendar days. 2026-03-29 and 2026-10-25 are the two switches (both Sundays).
  const CASES: [string, string, string, string, string, number][] = [
    [
      "Monday",
      "2026-11-02T12:00:00Z",
      "2026-11-02",
      "2026-11-03",
      "2026-11-09",
      7,
    ],
    [
      "Sunday",
      "2026-11-01T12:00:00Z",
      "2026-11-01",
      "2026-11-02",
      "2026-11-02",
      1,
    ],
    [
      "Saturday before the spring switch",
      "2026-03-28T10:00:00Z",
      "2026-03-28",
      "2026-03-29",
      "2026-03-30",
      2,
    ],
    [
      "after midnight on the spring switch day (Stockholm 00:30, UTC still the 28th)",
      "2026-03-28T23:30:00Z",
      "2026-03-29",
      "2026-03-30",
      "2026-03-30",
      1,
    ],
    [
      "the spring switch Sunday",
      "2026-03-29T10:00:00Z",
      "2026-03-29",
      "2026-03-30",
      "2026-03-30",
      1,
    ],
    [
      "Saturday before the autumn switch",
      "2026-10-24T10:00:00Z",
      "2026-10-24",
      "2026-10-25",
      "2026-10-26",
      2,
    ],
    [
      "after midnight on the autumn switch day (Stockholm 00:30, UTC still the 24th)",
      "2026-10-24T22:30:00Z",
      "2026-10-25",
      "2026-10-26",
      "2026-10-26",
      1,
    ],
    [
      "the autumn switch Sunday",
      "2026-10-25T10:00:00Z",
      "2026-10-25",
      "2026-10-26",
      "2026-10-26",
      1,
    ],
    [
      "month end",
      "2026-10-31T10:00:00Z",
      "2026-10-31",
      "2026-11-01",
      "2026-11-02",
      2,
    ],
    [
      "late evening in Stockholm, still the day before in New York",
      "2026-11-02T23:30:00Z",
      "2026-11-03",
      "2026-11-04",
      "2026-11-09",
      6,
    ],
  ];

  describe.each(ZONES)("browser zone %s", (zone) => {
    it.each(CASES)(
      "%s: Stockholm today, tomorrow, next Monday and the 23:59 instants",
      (_label, instant, today, tomorrow, monday, toMonday) => {
        process.env.TZ = zone;
        const now = new Date(instant);
        expect(ownerDayPlus(now, 0)).toBe(today);
        expect(ownerDayPlus(now, 1)).toBe(tomorrow);
        expect(ownerDaysToNextMonday(now)).toBe(toMonday);
        expect(ownerDayPlus(now, toMonday)).toBe(monday);
        // The triage moves are 23:59 on those Stockholm days, the instant ownerEndOfDay gives, in every zone.
        expect(triageDueAt(now, "today")).toBe(ownerEndOfDay(today));
        expect(triageDueAt(now, "tomorrow")).toBe(ownerEndOfDay(tomorrow));
        expect(triageDueAt(now, "nextWeek")).toBe(ownerEndOfDay(monday));
        // And each reads back as that day in Stockholm, at 23:59.
        const stockholm = new Intl.DateTimeFormat("sv-SE", {
          timeZone: "Europe/Stockholm",
          dateStyle: "short",
          timeStyle: "short",
        });
        expect(stockholm.format(new Date(triageDueAt(now, "today")))).toBe(
          `${today} 23:59`,
        );
        expect(stockholm.format(new Date(triageDueAt(now, "tomorrow")))).toBe(
          `${tomorrow} 23:59`,
        );
        expect(stockholm.format(new Date(triageDueAt(now, "nextWeek")))).toBe(
          `${monday} 23:59`,
        );
      },
    );
  });

  it("gives literal instants around both switches (CET before and after, CEST on the switch day)", () => {
    process.env.TZ = "Pacific/Auckland";
    // Friday 27 Mar 2026, Stockholm CET: tomorrow is Saturday 28 Mar; next Monday is 30 Mar (CEST, UTC+2).
    const now = new Date("2026-03-27T12:00:00Z");
    expect(triageDueAt(now, "tomorrow")).toBe("2026-03-28T22:59:00.000Z");
    expect(triageDueAt(now, "nextWeek")).toBe("2026-03-30T21:59:00.000Z");
    // Friday 23 Oct 2026, CEST: tomorrow is 24 Oct (CEST), next Monday 26 Oct (CET, UTC+1) after the switch.
    const autumn = new Date("2026-10-23T12:00:00Z");
    expect(triageDueAt(autumn, "tomorrow")).toBe("2026-10-24T21:59:00.000Z");
    expect(triageDueAt(autumn, "nextWeek")).toBe("2026-10-26T22:59:00.000Z");
  });

  it("counts 1 day to next Monday from a Sunday and 7 from a Monday, 6 from a Tuesday", () => {
    expect(ownerDaysToNextMonday(new Date("2026-11-08T12:00:00Z"))).toBe(1);
    expect(ownerDaysToNextMonday(new Date("2026-11-09T12:00:00Z"))).toBe(7);
    expect(ownerDaysToNextMonday(new Date("2026-11-10T12:00:00Z"))).toBe(6);
    // Saturday 21:00 in Stockholm is already Sunday 05:00 in Tokyo: still 2 days to Monday by the Stockholm calendar.
    process.env.TZ = "Asia/Tokyo";
    expect(ownerDaysToNextMonday(new Date("2026-11-07T20:00:00Z"))).toBe(2);
    // Monday 00:30 in Stockholm is still Sunday 18:30 in New York: 7 days, not 1.
    process.env.TZ = "America/New_York";
    expect(ownerDaysToNextMonday(new Date("2026-11-08T23:30:00Z"))).toBe(7);
    // Sunday 00:30 in Stockholm is still Saturday 18:30 in New York: 1 day, not 2.
    expect(ownerDaysToNextMonday(new Date("2026-11-07T23:30:00Z"))).toBe(1);
  });
});
