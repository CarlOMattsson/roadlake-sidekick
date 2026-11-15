// Property-based fuzzing of the owner's calendar day: `ownerNoon` turns a YYYY-MM-DD from the server or a
// date field into an instant, and `ownerToday` reads the day back. Every zone the runtime knows is a candidate.
import fc from "fast-check";
import { describe, expect, it } from "vitest";

import { ownerNoon, ownerToday } from "@/features/mcp-apps/app-timezone";

const ZONES = Intl.supportedValuesOf("timeZone");
const pad = (value: number, width: number) =>
  String(value).padStart(width, "0");

/** Days in a month of the proleptic Gregorian calendar, `month` 1..12. */
function daysIn(year: number, month: number): number {
  const leap = (year % 4 === 0 && year % 100 !== 0) || year % 400 === 0;
  return [31, leap ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31][
    month - 1
  ]!;
}

describe("ownerNoon and ownerToday (fuzzed)", () => {
  it("noon of a real day is that same day in the owner's zone", () => {
    fc.assert(
      fc.property(
        fc.date({
          min: new Date("1900-01-01T00:00:00Z"),
          max: new Date("2200-12-31T00:00:00Z"),
          noInvalidDate: true,
        }),
        fc.constantFrom(...ZONES),
        (moment, zone) => {
          const day = moment.toISOString().slice(0, 10);
          const noon = ownerNoon(day, zone);
          expect(noon).toBeDefined();
          expect(ownerToday(zone, new Date(noon!))).toBe(day);
        },
      ),
      { numRuns: 300 },
    );
  });

  it("answers undefined for a day that is shaped right but does not exist", () => {
    fc.assert(
      fc.property(
        fc.integer({ min: 1, max: 9999 }),
        fc.integer({ min: 0, max: 99 }),
        fc.integer({ min: 0, max: 99 }),
        (year, month, date) => {
          const day = `${pad(year, 4)}-${pad(month, 2)}-${pad(date, 2)}`;
          const real =
            month >= 1 &&
            month <= 12 &&
            date >= 1 &&
            date <= daysIn(year, month);
          const noon = ownerNoon(day, "UTC");
          if (real) expect(noon?.slice(0, 10)).toBe(day);
          else expect(noon).toBeUndefined();
        },
      ),
      { numRuns: 500 },
    );
  });

  it("never throws, whatever text and zone it is given", () => {
    fc.assert(
      fc.property(fc.string(), fc.option(fc.string()), (day, zone) => {
        const noon = ownerNoon(day, zone ?? undefined);
        if (noon !== undefined)
          expect(Number.isNaN(Date.parse(noon))).toBe(false);
        expect(ownerToday(zone ?? undefined)).toMatch(/^\d{4}-\d{2}-\d{2}$/);
      }),
      { numRuns: 300 },
    );
  });
});
