import { afterEach, describe, expect, it, vi } from "vitest";
import { ownerNoon, ownerToday } from "./app-timezone";

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
});
