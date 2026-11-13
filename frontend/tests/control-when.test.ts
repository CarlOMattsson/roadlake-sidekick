import { describe, expect, it } from "vitest";

import { whenText } from "@/features/control-app/when";

const now = new Date("2026-11-01T10:00:00Z");
const minutesBefore = (minutes: number) =>
  new Date(now.getTime() - minutes * 60_000).toISOString();

describe("whenText in Swedish", () => {
  it.each([
    ["30 s sedan", new Date(now.getTime() - 30_000).toISOString(), "nyss"],
    ["12 min sedan", minutesBefore(12), "för 12 min sedan"],
    ["08:05 UTC, samma dag i Stockholm", "2026-11-01T08:05:00Z", "idag 09:05"],
    ["igår 14:30 lokal tid", "2026-10-31T13:30:00Z", "igår 14:30"],
    ["47 h sedan, förrgår i Stockholm", "2026-10-30T11:00:00Z", "30 okt"],
    ["30 okt 14:30, förrgår", "2026-10-30T13:30:00Z", "30 okt"],
    ["30 okt 23:59, sista minuten förrgår", "2026-10-30T22:59:00Z", "30 okt"],
    ["31 okt 23:59, sista minuten igår", "2026-10-31T22:59:00Z", "igår 23:59"],
    ["29 okt, äldre än två dagar", "2026-10-29T13:30:00Z", "29 okt"],
    ["annat år, över två dygn", "2025-12-05T08:00:00Z", "5 dec 2025"],
    ["exakt en timme sedan", minutesBefore(60), "idag 10:00"],
  ])("%s", (_label, value, expected) => {
    expect(whenText(value, now, "sv")).toBe(expected);
  });

  it("keeps the clock only for today and yesterday, counted by the Stockholm calendar", () => {
    // 47 h 59 min ago is 30 Oct 11:01 in Stockholm: the day before yesterday, so the date alone.
    expect(whenText(minutesBefore(2 * 24 * 60 - 1), now, "sv")).toBe("30 okt");
    expect(whenText(minutesBefore(2 * 24 * 60), now, "sv")).toBe("30 okt");
    expect(whenText("2026-10-29T08:00:00Z", now, "sv")).toBe("29 okt");
  });

  it("uses the Stockholm calendar day around midnight", () => {
    // 23:30 UTC is 00:30 the next day in Stockholm, so it is today there.
    expect(whenText("2026-10-31T23:30:00Z", now, "sv")).toBe("idag 00:30");
  });

  it("gives nothing for a missing or invalid value", () => {
    expect(whenText("", now, "sv")).toBe("");
    expect(whenText(null, now, "sv")).toBe("");
    expect(whenText(undefined, now, "sv")).toBe("");
    expect(whenText("inte ett datum", now, "sv")).toBe("");
  });
});

describe("whenText in English", () => {
  it.each([
    ["30 s ago", new Date(now.getTime() - 30_000).toISOString(), "just now"],
    ["12 min ago", minutesBefore(12), "12 min ago"],
    ["today", "2026-11-01T08:05:00Z", "today at 09:05"],
    ["yesterday", "2026-10-31T13:30:00Z", "yesterday at 14:30"],
    ["47 h ago, the day before yesterday", "2026-10-30T11:00:00Z", "30 Oct"],
    [
      "30 Oct 14:30, the day before yesterday",
      "2026-10-30T13:30:00Z",
      "30 Oct",
    ],
    ["31 Oct 23:59, yesterday", "2026-10-31T22:59:00Z", "yesterday at 23:59"],
    ["29 Oct, over two days", "2026-10-29T13:30:00Z", "29 Oct"],
    ["another year, over two days", "2025-12-05T08:00:00Z", "5 Dec 2025"],
  ])("%s", (_label, value, expected) => {
    expect(whenText(value, now, "en")).toBe(expected);
  });

  it("gives nothing for a missing or invalid value", () => {
    expect(whenText(null, now, "en")).toBe("");
    expect(whenText("inte ett datum", now, "en")).toBe("");
  });
});
