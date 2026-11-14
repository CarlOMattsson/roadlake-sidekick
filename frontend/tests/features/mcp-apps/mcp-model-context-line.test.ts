import { describe, expect, it } from "vitest";
import { modelContextLine } from "@/features/mcp-apps/sidekick-shell";
import { sidekickShellLabelsFor } from "@/features/mcp-apps/sidekick-shell-labels";
import type { NavEntry } from "@/features/mcp-apps/nav-state";

const sv = sidekickShellLabelsFor("sv");

// A lone surrogate is a code unit of a pair without its partner: it breaks the text.
const LONE_SURROGATE =
  /[\uD800-\uDBFF](?![\uDC00-\uDFFF])|(?<![\uD800-\uDBFF])[\uDC00-\uDFFF]/;

describe("modelContextLine", () => {
  it("collapses whitespace in a label and names the room, the label and the id", () => {
    const entry: NavEntry = {
      room: "contacts",
      view: "contact",
      id: "7",
      label: "Anna\n\nIgnore\tprevious  ",
    };
    expect(modelContextLine(sv, "contacts", entry)).toBe(
      "Visar Kontakter › Anna Ignore previous (id 7)",
    );
  });

  it("cuts a label of 200 characters to 80", () => {
    const entry: NavEntry = {
      room: "contacts",
      view: "contact",
      label: "a".repeat(200),
    };
    expect(modelContextLine(sv, "contacts", entry)).toBe(
      `Visar Kontakter › ${"a".repeat(80)}`,
    );
  });

  it("cuts an emoji label by code points, never through a surrogate pair", () => {
    const entry: NavEntry = {
      room: "contacts",
      view: "contact",
      label: "😀".repeat(100),
    };
    const line = modelContextLine(sv, "contacts", entry);
    expect(line).toBe(`Visar Kontakter › ${"😀".repeat(80)}`);
    expect(LONE_SURROGATE.test(line)).toBe(false);
  });

  it("leaves a journal entry's label out and names it by id only", () => {
    const entry: NavEntry = {
      room: "journal",
      view: "entry",
      id: "e1",
      label: "Hemlig dagbokstext",
    };
    const line = modelContextLine(sv, "journal", entry);
    expect(line).toBe("Visar Dagbok (id e1)");
    expect(line).not.toContain("Hemlig");
  });
});
