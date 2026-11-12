import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

// Ring column, buttons and links (designsystem §3 Listrad and Knappar). A pixel probe in a real browser checks the
// ring's column: every pixel under the ring, across its button and down its row, must mark the task done. These pin
// the CSS that gives that, and the button and link rules.
const css = (file: string) =>
  readFileSync(
    path.resolve(import.meta.dirname, "../src/features", file),
    "utf8",
  );

describe("ring column, button and link targets", () => {
  it("lets the board ring's target follow its button's width at every text size", () => {
    const work = css("work-app/work.css");
    // A fixed 48 left 40 px under an 88 px button at 200 % text where a tap opened the task.
    expect(work).toMatch(
      /button\.work-card-done::after \{[^}]*inset-inline-start: calc\(var\(--work-lead-hang\) - 2px\);\s*width: calc\(var\(--sk-lead-w\) \+ 4px\);/,
    );
    expect(work).not.toMatch(
      /button\.work-card-done::after \{[^}]*width: 48px;/,
    );
    // The button is the column's width and the row's height (min-height 0, so the row's 48 holds the target,
    // which its ::after covers), and the grid's first column is the same width plus the hang.
    expect(work).toMatch(
      /button\.work-card-done \{[^}]*width: var\(--sk-lead-w\);[^}]*min-width: var\(--sk-lead-w\);[^}]*height: var\(--sk-lead-h\);[^}]*min-height: 0;/,
    );
    expect(work).toMatch(
      /calc\(var\(--sk-lead-w\) \+ var\(--work-lead-hang\) \+ 2px\) minmax\(0, 1fr\)/,
    );
    // The agenda ring's target is its button, 2 past each side, over the whole line.
    expect(css("work-app/agenda.css")).toMatch(
      /\.work-agenda-line > button\.work-agenda-glyph::after \{[^}]*inset: 0 -2px;/,
    );
  });

  it("keeps the leading column at least 44 wide and the ring on the title line's middle", () => {
    const tokens = css("mcp-apps/ui/tokens.css");
    // The ring is 24 to 32 px (the icon size up to 133 % text, then 32), and the column is the ring plus 20.
    expect(tokens).toMatch(/--sk-ring-glyph: clamp\(24px, 1\.5rem, 32px\);/);
    expect(tokens).toMatch(
      /--sk-lead-w: max\(44px, calc\(var\(--sk-ring-glyph\) \+ 20px\)\);/,
    );
    expect(tokens).toMatch(
      /--sk-lead-hang: calc\(\(var\(--sk-ring-glyph\) - var\(--sk-lead-w\)\) \/ 2\);/,
    );
    // The title's padding is the row's --sk-row-pad (6), so the ring's padding is
    // --sk-row-pad + half a row line − half the ring.
    expect(css("work-app/agenda.css")).toMatch(
      /padding-top: calc\(\s*var\(--sk-row-pad\) \+ var\(--sk-type-row-line\) \/ 2 - var\(--sk-ring-glyph\) \/ 2\s*\);/,
    );
  });

  it("draws Markera klar as the screen's one primary, compact, last in the property block", () => {
    const view = readFileSync(
      path.resolve(
        import.meta.dirname,
        "../src/features/work-app/work-view-parts/task-frame.tsx",
      ),
      "utf8",
    );
    expect(view).toMatch(/"sk-btn--primary sk-btn--compact work-task-done"/);
    expect(view).toMatch(/"sk-btn--secondary sk-btn--compact work-task-done"/);
    expect(view).not.toMatch(/sk-btn--tonal/);
  });
});
