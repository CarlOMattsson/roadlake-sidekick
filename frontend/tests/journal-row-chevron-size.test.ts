// uc-16: the row › in Dagbok is the shared row glyph: --sk-chevron wide and high (24, 16 on a narrow frame), as in the
// other rooms, instead of the icon's own 24 px at every width. Reads the stylesheet, as journal-css-contract does.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const css = readFileSync(
  path.resolve(import.meta.dirname, "../src/features/journal-app/journal.css"),
  "utf8",
).replace(/\/\*[\s\S]*?\*\//g, "");

describe("Dagbok row chevron", () => {
  it("is sized by the shared --sk-chevron token in both axes", () => {
    const rule = css.match(
      /\.sidekick-journal \.journal-entry-chevron svg\s*\{([^}]*)\}/,
    );
    expect(rule, "chevron svg rule").not.toBeNull();
    expect(rule![1]).toMatch(/width:\s*var\(--sk-chevron\)/);
    expect(rule![1]).toMatch(/height:\s*var(?:\(--sk-chevron\))/);
  });

  it("turns 16 on a narrow frame as the contact and shopping rows do", () => {
    expect(css).toMatch(
      /@container sk-frame \(max-width: 399\.98px\) or \(max-width: 17\.25rem\)\s*\{\s*\.sidekick-journal\s*\{\s*--sk-chevron:\s*16px;/,
    );
  });
});
