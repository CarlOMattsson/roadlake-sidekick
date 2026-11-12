import { describe, expect, it } from "vitest";
import {
  hierarchyDetailLabelsEn,
  hierarchyDetailLabelsFor,
  hierarchyDetailLabelsSv,
} from "@/features/work-app/hierarchy/hierarchy-detail-labels";

/*
 * The words of hierarchy-detail-labels.ts: the Projects list's meta words and filter, and the words the Task and
 * Contact detail borrow. The list itself is tested in hierarchy-view.test.tsx.
 */

describe("detail labels", () => {
  it("keeps the Swedish and English detail words to the same keys", () => {
    expect(keyPaths(hierarchyDetailLabelsEn)).toEqual(
      keyPaths(hierarchyDetailLabelsSv),
    );
    for (const key of keyPaths(hierarchyDetailLabelsSv)) {
      expect(readPath(hierarchyDetailLabelsSv, key)).not.toBe("");
      expect(readPath(hierarchyDetailLabelsEn, key)).not.toBe("");
    }
  });

  it("picks the Swedish words for a Swedish locale and English otherwise", () => {
    expect(hierarchyDetailLabelsFor("sv-SE")).toBe(hierarchyDetailLabelsSv);
    expect(hierarchyDetailLabelsFor("en-GB")).toBe(hierarchyDetailLabelsEn);
  });

  it("says open Tasks with the right plural in both languages", () => {
    expect(hierarchyDetailLabelsSv.openTasks(0)).toBe("Inga öppna uppgifter");
    expect(hierarchyDetailLabelsSv.openTasks(1)).toBe("1 öppen uppgift");
    expect(hierarchyDetailLabelsSv.openTasks(3)).toBe("3 öppna uppgifter");
    expect(hierarchyDetailLabelsEn.openTasks(0)).toBe("No open tasks");
    expect(hierarchyDetailLabelsEn.openTasks(1)).toBe("1 open task");
    expect(hierarchyDetailLabelsEn.openTasks(3)).toBe("3 open tasks");
  });

  it("says overdue Tasks and the completed group with their counts", () => {
    expect(hierarchyDetailLabelsSv.overdue(1)).toBe("1 försenad");
    expect(hierarchyDetailLabelsSv.overdue(2)).toBe("2 försenade");
    expect(hierarchyDetailLabelsEn.overdue(2)).toBe("2 overdue");
    expect(hierarchyDetailLabelsSv.completedGroup(4)).toBe("Avslutade (4)");
    expect(hierarchyDetailLabelsEn.completedGroup(4)).toBe("Completed (4)");
  });

  it("keeps the words the Task and Contact detail borrow", () => {
    expect(hierarchyDetailLabelsSv.dueTomorrow).toBe("Imorgon");
    expect(hierarchyDetailLabelsEn.dueTomorrow).toBe("Tomorrow");
    expect(hierarchyDetailLabelsSv.changeStatus).toBe("Ändra status");
    expect(hierarchyDetailLabelsSv.aboutContact("Anna")).toBe("Om Anna");
    expect(hierarchyDetailLabelsEn.aboutContact("Anna")).toBe("About Anna");
    expect(hierarchyDetailLabelsSv.wayWords).toHaveLength(
      hierarchyDetailLabelsEn.wayWords.length,
    );
  });
});

/** Dotted paths to every leaf of a label set; functions count as leaves. */
function keyPaths(value: object, prefix = ""): string[] {
  return Object.entries(value as Record<string, unknown>)
    .flatMap(([key, entry]) =>
      entry !== null && typeof entry === "object"
        ? keyPaths(entry, `${prefix}${key}.`)
        : [`${prefix}${key}`],
    )
    .sort();
}

function readPath(value: object, dotted: string): unknown {
  return dotted
    .split(".")
    .reduce<unknown>(
      (node, key) => (node as Record<string, unknown>)[key],
      value,
    );
}
