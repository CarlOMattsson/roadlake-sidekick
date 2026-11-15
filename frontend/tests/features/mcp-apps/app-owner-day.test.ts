import { afterEach, describe, expect, it, vi } from "vitest";
import { ownerNoon, ownerToday } from "@/features/mcp-apps/app-timezone";

afterEach(() => {
  vi.useRealTimers();
  vi.unstubAllEnvs();
});

describe("ownerToday", () => {
  it("names the owner's calendar day when the instant is still the day before in UTC", () => {
    // 23:30 UTC on the 10th is 00:30 on the 11th in Stockholm (winter, UTC+1).
    expect(
      ownerToday("Europe/Stockholm", new Date("2026-11-10T23:30:00Z")),
    ).toBe("2026-11-11");
  });

  it("uses the zone named by the server, not the device or the default", () => {
    expect(
      ownerToday("America/Los_Angeles", new Date("2026-11-11T05:00:00Z")),
    ).toBe("2026-11-10");
  });

  it("falls back to the default zone for an unknown zone", () => {
    expect(ownerToday("Not/AZone", new Date("2026-11-10T23:30:00Z"))).toBe(
      "2026-11-11",
    );
  });
});

describe("ownerNoon", () => {
  it("is noon in the owner's zone, whatever zone the device is in", () => {
    for (const device of ["Pacific/Pago_Pago", "Pacific/Kiritimati", "UTC"]) {
      vi.stubEnv("TZ", device);
      expect(ownerNoon("2026-11-10", "Europe/Stockholm")).toBe(
        "2026-11-10T11:00:00.000Z",
      );
    }
  });

  it("follows daylight saving time of the day itself", () => {
    expect(ownerNoon("2026-07-10", "Europe/Stockholm")).toBe(
      "2026-07-10T10:00:00.000Z",
    );
  });

  it("rejects malformed days", () => {
    expect(ownerNoon("2026-1-1")).toBeUndefined();
  });

  it("rejects a well-shaped day that does not exist instead of rolling it over", () => {
    for (const day of ["2026-02-31", "2026-13-01", "2026-00-10", "2026-04-00"])
      expect(ownerNoon(day, "Europe/Stockholm")).toBeUndefined();
  });

  it("keeps a year below 100 as written", () => {
    expect(ownerNoon("0099-05-01", "UTC")).toBe("0099-05-01T12:00:00.000Z");
  });
});
