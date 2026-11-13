import { describe, expect, it } from "vitest";

import { readStylesheet } from "./helpers/stylesheet";

// Touch targets (designsystem §2 Träffytor) that no browser spec reaches yet: a held shopping row's Undo and the
// Kontroll room's tabs and rows, which the simulated host does not open. The board ring, the room strip's tabs and
// Kontakter's + are measured in tests/e2e/work-hit-targets-mcp-app.spec.ts, the Agenda's in layout-mcp-app.spec.ts.
// Each rule is looked up by its selector and compared declaration by declaration.
describe("touch targets", () => {
  it("keeps a held shopping row's Undo target inside its own row", () => {
    const shopping = readStylesheet("features/shopping-app/shopping.css");

    // The title stays 13 down (centre 24) and Undo starts 4 down, so its target (4 past every edge) starts on the
    // row top (the row is a button beside the ring; its first line starts at --shopping-row-top, 13 at 100 % text).
    expect(
      shopping.rule(".sidekick-shopping .shopping-store-line")[
        "--shopping-row-top"
      ],
    ).toMatch(/^max\(11px, calc\(\(48px - var\(--sk-type-row-line\)\) \/ 2\)/);
    expect(
      shopping.rule(".sidekick-shopping .shopping-held-item > .shopping-undo")[
        "margin-top"
      ],
    ).toBe("calc((var(--sk-tap-lg) - var(--sk-compact)) / 2)");
  });

  it("keeps Kontroll's tabs 48 high", () => {
    expect(
      readStylesheet("features/control-app/control.css").rule(
        ".sidekick-control .sk-segmented .sk-segmented__option",
      ),
    ).toMatchObject({
      flex: "1 0 0",
      "min-width": "max-content",
      height: "48px",
      "min-height": "48px",
      margin: "-4px 0 -1px",
      padding: "6px var(--sk-s3) 0",
    });
  });

  it("gives Kontroll's rows the row template: --sk-row-pad over and under, a 48 floor, the action across both lines, and no margin on the meta line", () => {
    const control = readStylesheet("features/control-app/control.css");
    const row = control.rule(".sidekick-control .control-row");
    const secondary = control.rule(".sidekick-control .control-row-secondary");

    expect(row).toMatchObject({
      display: "grid",
      padding: "var(--sk-row-pad) 0",
      "min-height": "var(--sk-row-min)",
      "align-items": "center",
    });
    // The old row-in-room margin (0.5rem between rows) is gone: the row's own padding separates the rows.
    expect(control.has(".sk-rooms__pane .sidekick-control .control-row")).toBe(
      false,
    );
    expect(secondary["margin-top"]).toBeUndefined();
    // One meta line, cut with an ellipsis.
    expect(secondary).toMatchObject({
      "white-space": "nowrap",
      "text-overflow": "ellipsis",
    });
    // The action stands in the second column across both rows, centred on the row.
    expect(
      control.rule(".sidekick-control .control-row-action")["grid-area"],
    ).toBe("1 / 2 / 3");
  });
});
