import { describe, expect, it } from "vitest";
import {
  agendaGroupLabel,
  agendaLabelsEn,
  agendaLabelsFor,
  agendaLabelsSv,
} from "@/features/work-app/agenda/agenda-labels";
import {
  boardLabelsEn,
  boardLabelsFor,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  moveAllEn,
  moveAllSv,
} from "@/features/work-app/shared/move-all-labels";

/** Every key path of a label set, with a function marked by its arity: the sets must agree on both. */
function shape(value: unknown, prefix = ""): string[] {
  if (typeof value === "function") return [`${prefix}()${value.length}`];
  if (value && typeof value === "object")
    return Object.entries(value).flatMap(([key, child]) =>
      shape(child, prefix ? `${prefix}.${key}` : key),
    );
  return [prefix];
}

describe("Work label sets", () => {
  it.each([
    ["agenda", agendaLabelsEn, agendaLabelsSv],
    ["board", boardLabelsEn, boardLabelsSv],
    ["move all", moveAllEn, moveAllSv],
    ["shared", workEn, workSv],
  ])("keeps the English and Swedish key sets of %s identical", (_, en, sv) => {
    expect(shape(en).sort()).toEqual(shape(sv).sort());
  });

  it("picks the words of a work locale and falls back to English", () => {
    expect(agendaLabelsFor("sv-SE")).toBe(agendaLabelsSv);
    expect(agendaLabelsFor("en-GB")).toBe(agendaLabelsEn);
    expect(boardLabelsFor("sv-SE")).toBe(boardLabelsSv);
    expect(boardLabelsFor("en-GB")).toBe(boardLabelsEn);
  });

  it("shows an agenda group it does not know as it arrived", () => {
    expect(agendaGroupLabel(agendaLabelsSv, "overdue")).toBe("Försenade");
    expect(agendaGroupLabel(agendaLabelsEn, "someday")).toBe("someday");
  });

  it("keeps the agenda and board words out of the shared set", () => {
    const shared = Object.keys(workEn);
    for (const key of ["agendaGroup", "boardConflict", "rowChangeFailed"])
      expect(shared).not.toContain(key);
  });
});
