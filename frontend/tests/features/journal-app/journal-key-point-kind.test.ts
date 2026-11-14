import { describe, expect, it } from "vitest";

import {
  KEY_POINT_KINDS,
  isKeyPointKind,
  normalizeKeyPoints,
} from "@/features/journal-app/draft-review-parts/edit-values";
import type { JournalDraft } from "@/features/journal-app/transport";

describe("key point kinds", () => {
  it.each(KEY_POINT_KINDS)("accepts %s", (kind) => {
    expect(isKeyPointKind(kind)).toBe(true);
  });

  it.each(["insight", "", "Fact"])("refuses %j", (kind) => {
    expect(isKeyPointKind(kind)).toBe(false);
  });

  it("turns a kind the schema does not list into a fact and says it changed", () => {
    // A kind a newer server might send; the type only allows the contract's kinds.
    const unknown = "insight" as JournalDraft["key_points"][number]["kind"];
    const draft = {
      key_points: [
        { kind: unknown, text: "Något nytt." },
        { kind: "decision", text: "Valde A." },
      ],
    } as JournalDraft;
    const result = normalizeKeyPoints(draft);
    expect(result.changed).toBe(true);
    expect(result.draft.key_points).toEqual([
      { kind: "fact", text: "Något nytt." },
      { kind: "decision", text: "Valde A." },
    ]);
  });
});
