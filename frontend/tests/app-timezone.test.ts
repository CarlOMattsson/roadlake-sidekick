import { afterEach, describe, expect, it } from "vitest";

import {
  appTimeZone,
  ownerDateFormat,
  ownerToday,
} from "@/features/mcp-apps/app-timezone";
import {
  ownerEndOfDay,
  relativeDue,
  workDate,
} from "@/features/mcp-apps/ui/due";
import { dateInputValue } from "@/features/work-app/task-edit";

// SIDEKICK_OWNER_TIMEZONE arrives as a meta tag in the app document. The tests declare it in the
// real document, the way the host loads the app, and clear it again afterwards.
function declare(zone: string | undefined): void {
  document.head
    .querySelectorAll('meta[name="sidekick-owner-timezone"]')
    .forEach((meta) => meta.remove());
  if (zone === undefined) return;
  const meta = document.createElement("meta");
  meta.name = "sidekick-owner-timezone";
  meta.content = zone;
  document.head.append(meta);
}

afterEach(() => declare(undefined));

describe("the owner time zone of the app", () => {
  it("is Europe/Stockholm when the backend declares nothing", () => {
    expect(appTimeZone()).toBe("Europe/Stockholm");
  });

  it("is the declared zone", () => {
    declare("America/New_York");
    expect(appTimeZone()).toBe("America/New_York");
  });

  it("falls back to Stockholm for a zone the host does not know", () => {
    declare("Mars/Olympus_Mons");
    expect(appTimeZone()).toBe("Europe/Stockholm");
  });

  it("follows the declaration when it changes", () => {
    declare("Asia/Tokyo");
    expect(appTimeZone()).toBe("Asia/Tokyo");
    declare(undefined);
    expect(appTimeZone()).toBe("Europe/Stockholm");
  });

  it("formats clocks in the declared zone", () => {
    const at = new Date("2026-11-04T12:00:00Z");
    const clock = () =>
      ownerDateFormat("en-GB", { hour: "2-digit", minute: "2-digit" }).format(
        at,
      );
    expect(clock()).toBe("13:00");
    declare("Asia/Tokyo");
    expect(clock()).toBe("21:00");
  });
});

describe("dates follow the declared owner zone", () => {
  // 2026-11-04T23:30Z is already Thursday 5 Nov in Stockholm and Tokyo, still Wednesday 4 Nov in New York.
  const instant = "2026-11-04T23:30:00Z";
  const now = new Date("2026-11-04T12:00:00Z");

  it("reads the due day in the declared zone", () => {
    expect(dateInputValue(instant)).toBe("2026-11-05");
    declare("America/New_York");
    expect(dateInputValue(instant)).toBe("2026-11-04");
    declare("Asia/Tokyo");
    expect(dateInputValue(instant)).toBe("2026-11-05");
  });

  it("counts today and relative labels in the declared zone", () => {
    expect(workDate(instant, now, "en-GB", { inline: true })).toBe("tomorrow");
    declare("America/New_York");
    expect(workDate(instant, now, "en-GB", { inline: true })).toBe("today");
    expect(relativeDue(instant, now, "en").tone).toBe("today");
  });

  it("saves the picked day as 23:59 in the declared zone and reads the same day back", () => {
    declare("America/New_York");
    const due = ownerEndOfDay("2026-11-04");
    expect(due).toBe("2026-11-05T04:59:00.000Z"); // 23:59 EST, UTC-5
    expect(dateInputValue(due)).toBe("2026-11-04");
    declare("Asia/Tokyo");
    expect(ownerEndOfDay("2026-11-04")).toBe("2026-11-04T14:59:00.000Z");
  });
});

describe("the owner's today", () => {
  // 23:30 UTC on 4 November is 00:30 on the 5th in Stockholm and still the 4th in New York.
  const midnight = new Date("2026-11-04T23:30:00Z");

  it("is the owner's calendar day, not the device's or UTC's", () => {
    expect(ownerToday(undefined, midnight)).toBe("2026-11-05");
    declare("America/New_York");
    expect(ownerToday(undefined, midnight)).toBe("2026-11-04");
  });

  it("follows the zone a server result names, e.g. on the phone that has no meta", () => {
    expect(ownerToday("America/New_York", midnight)).toBe("2026-11-04");
    expect(ownerToday("Europe/Stockholm", midnight)).toBe("2026-11-05");
  });

  it("ignores a zone the host does not know", () => {
    expect(ownerToday("Mars/Olympus_Mons", midnight)).toBe("2026-11-05");
  });

  it("turns at Stockholm midnight on the clock-change nights", () => {
    // 2026-03-29, spring forward: UTC+1 until 01:00 UTC; 23:00 UTC is Stockholm midnight.
    expect(ownerToday(undefined, new Date("2026-03-28T22:59:00Z"))).toBe(
      "2026-03-28",
    );
    expect(ownerToday(undefined, new Date("2026-03-28T23:00:00Z"))).toBe(
      "2026-03-29",
    );
    // 2026-10-25, fall back: UTC+2 until 01:00 UTC; 22:00 UTC the evening before is midnight.
    expect(ownerToday(undefined, new Date("2026-10-24T21:59:00Z"))).toBe(
      "2026-10-24",
    );
    expect(ownerToday(undefined, new Date("2026-10-24T22:00:00Z"))).toBe(
      "2026-10-25",
    );
    expect(ownerToday(undefined, new Date("2026-10-25T00:30:00Z"))).toBe(
      "2026-10-25",
    );
    expect(ownerToday(undefined, new Date("2026-10-25T01:30:00Z"))).toBe(
      "2026-10-25",
    );
    expect(ownerToday(undefined, new Date("2026-10-25T22:59:00Z"))).toBe(
      "2026-10-25",
    );
    expect(ownerToday(undefined, new Date("2026-10-25T23:00:00Z"))).toBe(
      "2026-10-26",
    );
  });
});
