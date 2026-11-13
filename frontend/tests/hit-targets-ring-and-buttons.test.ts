import { describe, expect, it } from "vitest";

import { readStylesheet } from "./helpers/stylesheet";

// Ring column, buttons and links (designsystem §3 Listrad and Knappar). A pixel probe in a real browser checks the
// ring's column: every pixel under the ring, across its button and down its row, must mark the task done. These pin
// the CSS that gives that, looked up by selector and compared declaration by declaration, and the button and link
// rules.
const BOARD_RING =
  '.sidekick-work .work-board[data-layout="single"] .work-list > li.work-card > .work-card-head > button.work-card-done';

describe("ring column, button and link targets", () => {
  it("lets the board ring's target follow its button's width at every text size", () => {
    const work = readStylesheet("features/work-app/shell/work.css");
    const agenda = readStylesheet("features/work-app/agenda/agenda.css");

    // A fixed 48 left 40 px under an 88 px button at 200 % text where a tap opened the task.
    const target = work.rule(`${BOARD_RING}::after`);
    expect(target["inset-inline-start"]).toBe(
      "calc(var(--work-lead-hang) - 2px)",
    );
    expect(target.width).toBe("calc(var(--sk-lead-w) + 4px)");
    // The button is the column's width and the row's height (min-height 0, so the row's 48 holds the target,
    // which its ::after covers).
    expect(work.rule(BOARD_RING)).toMatchObject({
      width: "var(--sk-lead-w)",
      "min-width": "var(--sk-lead-w)",
      height: "var(--sk-lead-h)",
      "min-height": "0",
    });
    // The grid's first column is the same width plus the hang.
    const columns = work.rules
      .map((rule) => rule.declarations["grid-template-columns"])
      .filter((value) => value !== undefined);
    expect(
      columns.some((value) =>
        value.startsWith(
          "calc(var(--sk-lead-w) + var(--work-lead-hang) + 2px) minmax(0, 1fr)",
        ),
      ),
    ).toBe(true);
    // The agenda ring's target is its button, 2 past each side, over the whole line.
    expect(
      agenda.rule(
        ".sidekick-work .work-agenda-line > button.work-agenda-glyph::after",
      ).inset,
    ).toBe("0 -2px");
  });

  it("keeps the leading column at least 44 wide and the ring on the title line's middle", () => {
    const root = readStylesheet("features/mcp-apps/ui/tokens.css").rule(
      ":root",
    );

    // The ring is 24 to 32 px (the icon size up to 133 % text, then 32), and the column is the ring plus 20.
    expect(root["--sk-ring-glyph"]).toBe("clamp(24px, 1.5rem, 32px)");
    expect(root["--sk-lead-w"]).toBe(
      "max(44px, calc(var(--sk-ring-glyph) + 20px))",
    );
    expect(root["--sk-lead-hang"]).toBe(
      "calc((var(--sk-ring-glyph) - var(--sk-lead-w)) / 2)",
    );
    // The title's padding is the row's --sk-row-pad (6), so the ring's padding is
    // --sk-row-pad + half a row line − half the ring.
    const paddings = readStylesheet("features/work-app/agenda/agenda.css")
      .rules.map((rule) => rule.declarations["padding-top"])
      .filter((value) => value !== undefined);
    expect(paddings).toContain(
      "calc(var(--sk-row-pad) + var(--sk-type-row-line) / 2 - var(--sk-ring-glyph) / 2)",
    );
  });
});
