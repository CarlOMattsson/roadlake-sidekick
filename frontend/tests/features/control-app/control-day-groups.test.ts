import { describe, expect, it } from "vitest";

import { groupByDay } from "@/features/control-app/day-groups";
import { roomOfKind } from "@/features/control-app/kind-room";

// Friday 20 November 2026, midday in the owner's zone, so the day does not depend on the zone's offset.
const now = new Date("2026-11-20T11:00:00Z");

type Row = { at: string; name: string };
const rowsOf = (...times: string[]): Row[] =>
  times.map((at, index) => ({ at, name: `r${index}` }));
const groupsOf = (rows: Row[], locale: "sv" | "en") =>
  groupByDay(rows, (row) => row.at, now, locale);

describe("groupByDay", () => {
  it("names today, yesterday and an older day, one group per day, in the order given (Swedish)", () => {
    const groups = groupsOf(
      rowsOf(
        "2026-11-20T09:00:00Z",
        "2026-11-20T07:00:00Z",
        "2026-11-19T12:00:00Z",
        "2026-11-17T12:00:00Z",
      ),
      "sv",
    );
    expect(groups.map((group) => group.heading)).toEqual([
      "Idag",
      "Igår",
      "tis 17 nov",
    ]);
    expect(groups.map((group) => group.rows.map((row) => row.name))).toEqual([
      ["r0", "r1"],
      ["r2"],
      ["r3"],
    ]);
  });

  it("says the same in English", () => {
    const groups = groupsOf(
      rowsOf(
        "2026-11-20T09:00:00Z",
        "2026-11-19T12:00:00Z",
        "2026-11-17T12:00:00Z",
      ),
      "en",
    );
    expect(groups.map((group) => group.heading)).toEqual([
      "Today",
      "Yesterday",
      "Tue 17 Nov",
    ]);
  });

  it("gives a day further back than a week only its date, and the year when it is not this year", () => {
    const groups = groupsOf(
      rowsOf("2026-11-05T12:00:00Z", "2025-12-24T12:00:00Z"),
      "sv",
    );
    expect(groups.map((group) => group.heading)).toEqual([
      "5 nov",
      "24 dec 2025",
    ]);
  });

  it("counts a time ahead of now as today, and keeps a row with no readable time under no heading", () => {
    const groups = groupsOf(
      rowsOf("2026-11-22T12:00:00Z", "2026-11-20T08:00:00Z", "not a time"),
      "sv",
    );
    expect(groups.map((group) => group.heading)).toEqual(["Idag", ""]);
    expect(groups[0]?.rows).toHaveLength(2);
  });

  it("has no groups for no rows", () => {
    expect(groupsOf([], "sv")).toEqual([]);
  });
});

describe("roomOfKind", () => {
  it.each([
    ["task", "work"],
    ["process_run", "work"],
    ["contact_task_link", "contacts"],
    ["journal_entry", "journal"],
    ["shopping_item", "shopping"],
  ] as const)("%s lives in %s", (kind, room) => {
    expect(roomOfKind(kind)).toBe(room);
  });

  it("knows no room for a reference or an unknown kind", () => {
    expect(roomOfKind("external_reference")).toBeUndefined();
    expect(roomOfKind("something_new")).toBeUndefined();
  });
});
