// Journal CSS contract (mobile test 2026-11-02, 320 px, redesigned 2026-11-04). The week strip is seven equal
// columns at every width and never scrolls, the day view's title row and step arrows are laid out as the design
// says, the chosen Godkänn/Avslå option takes its status tone, the decision bar is sticky only above 400 px, and
// the quiet buttons that lead a line align with the heading. The test reads journal.css and the TSX sources; it
// changes no CSS.
import { describe, expect, it } from "vitest";

import {
  cssRules,
  declares,
  readCss,
  ruleFor as findRule,
} from "./helpers/css-contract";
import { readSource } from "./helpers/source-files";

const read = (file: string) => readSource(`features/journal-app/${file}`);
const css = readCss("journal-app/journal.css");

const rules = cssRules(css);

const ruleFor = (selector: string) => findRule(rules, selector);

describe("week strip fits seven days at 320 px, without scrolling", () => {
  // The week is seven equal tracks shared by the strip's width (the arrows sit on the title row above, not beside
  // the week), so at 320 px every day has room. Only below about 250 px (tracks under 30 px) does it scroll.
  it("the week is seven equal tracks, 4 px apart and 2 px below 25rem", () => {
    const week = ruleFor(".sidekick-journal .sk-day-strip-week");
    expect(week, "week rule").toBeDefined();
    expect(
      declares(week!, "grid-template-columns", "repeat(7, minmax(30px, 1fr))"),
    ).toBe(true);
    expect(declares(week!, "column-gap", "var(--sk-s1)")).toBe(true);
    expect(
      /@media \(max-width: 24\.99rem\) \{\s*\.sidekick-journal \.sk-day-strip-week \{\s*column-gap: 2px;/.test(
        css,
      ),
      "narrow gap rule",
    ).toBe(true);
  });

  it("the summary, the empty line and the heading under the strip or the summary keep their air, and the tell-more button is gone from the content", () => {
    // The summary: body size on the row title's line height.
    const summary = ruleFor(".sidekick-journal .journal-day-summary > p");
    expect(summary, "summary rule").toBeDefined();
    expect(summary!.declarations).toMatch(/var\(--sk-type-row-line\)/);
    // A day being opened for writing says only its sentence: 12 (s3) under the strip.
    const empty = ruleFor(".sidekick-journal .journal-empty");
    expect(empty, "empty rule").toBeDefined();
    expect(declares(empty!, "margin", "var(--sk-s3) 0 0")).toBe(true);
    // An empty day's empty state stands 12 under the strip too, in the family's own state.
    const emptyState = ruleFor(
      ".sidekick-journal .journal-empty-state > .sk-empty",
    );
    expect(emptyState, "empty state rule").toBeDefined();
    expect(declares(emptyState!, "padding-top", "var(--sk-s3)")).toBe(true);
    // The first heading after the strip or after the summary (the + moved to the title row): 16 (s4).
    const heading = ruleFor(
      ".sidekick-journal :is(.sk-day-strip, .journal-day-summary) + h3",
    );
    expect(heading, "heading rule").toBeDefined();
    expect(declares(heading!, "margin-top", "var(--sk-s4)")).toBe(true);
    expect(css).not.toMatch(/journal-tell-more\) \+ h3/);
    expect(css).not.toMatch(/journal-day-summary \+ \.journal-tell-more/);
    // The old whole button and its hint are gone from the stylesheet.
    expect(css).not.toMatch(/journal-tell-more/);
    expect(css).not.toMatch(/journal-tell-hint/);
    // The + panel's two real buttons (Claude asks, or the user writes) are 48 tall, never the compact form.
    const choice = ruleFor(
      ".sidekick-journal .journal-add-panel > .journal-add-choice",
    );
    expect(choice, "add panel button rule").toBeDefined();
    expect(declares(choice!, "min-height", "var(--sk-tap-lg)")).toBe(true);
    const writeSelf = ruleFor(".sidekick-journal .journal-write-self");
    expect(writeSelf, "write-yourself button rule").toBeDefined();
    expect(declares(writeSelf!, "min-height", "var(--sk-tap-lg)")).toBe(true);
  });

  it("the day's + in the title row is the round ink + of the list views, 7 before ⋯", () => {
    const add = ruleFor(
      ".sidekick-journal .sk-day-strip-tools > .journal-day-add",
    );
    expect(add, "+ rule").toBeDefined();
    // A 32 ink disc in the 48 box, as the + of the list views (--sk-plus), in px as the head's other boxes.
    expect(declares(add!, "padding", "8px")).toBe(true);
    expect(declares(add!, "margin-inline-end", "7px")).toBe(true);
    expect(declares(add!, "align-content", "center")).toBe(true);
    const glyph = ruleFor(
      ".sidekick-journal .sk-day-strip-tools > .journal-day-add svg",
    );
    expect(glyph, "+ glyph rule").toBeDefined();
    expect(declares(glyph!, "width", "24px")).toBe(true);
    expect(declares(glyph!, "height", "24px")).toBe(true);
  });

  it("the week scrolls inside itself only as a narrow fallback, without scroll snap", () => {
    const week = ruleFor(".sidekick-journal .sk-day-strip-week");
    expect(week, "week rule").toBeDefined();
    expect(declares(week!, "overflow-x", "auto")).toBe(true);
    expect(week!.declarations).not.toMatch(/scroll-snap/);
  });

  it("the title row, the week row and the day cells are laid out as the design says", () => {
    // The day view's head: a grid with the title and ⋯ on one row and the week row "‹ 29 okt–4 nov ›"
    // under it at the start, the same at every width and text size. 12 under the room strip (margin-top --sk-s3).
    const head = ruleFor(".sidekick-journal .sk-day-strip-head");
    expect(head, "title row rule").toBeDefined();
    expect(declares(head!, "display", "grid")).toBe(true);
    expect(
      declares(head!, "grid-template-columns", "minmax(0, 1fr) auto"),
    ).toBe(true);
    expect(
      declares(head!, "grid-template-areas", '"title tools" "arrows arrows"'),
    ).toBe(true);
    expect(declares(head!, "column-gap", "0")).toBe(true);
    // The title stands as far under the room strip as every room's first line.
    expect(declares(head!, "margin-top", "var(--sk-s3)")).toBe(true);
    // One form at every width: no data-today-button rule and no narrow-container rule for the head any more.
    expect(css).not.toMatch(/data-today-button/);
    expect(css).not.toMatch(
      /@container sk-frame \(max-width: 399\.98px\) or \(max-width: 17\.25rem\) \{\s*\.sidekick-journal \.sk-day-strip-head \{/,
    );
    // The head's icon buttons are 48 × 48 in px, so the targets are the same at every text size, the glyph 24.
    const headButtons = ruleFor(
      ".sidekick-journal .sk-day-strip-head .sk-iconbtn",
    );
    expect(headButtons, "head icon buttons rule").toBeDefined();
    for (const property of ["width", "min-width", "height", "min-height"]) {
      expect(declares(headButtons!, property, "48px"), property).toBe(true);
    }
    const headGlyphs = ruleFor(
      ".sidekick-journal .sk-day-strip-head .sk-iconbtn svg",
    );
    expect(headGlyphs, "head glyph rule").toBeDefined();
    expect(declares(headGlyphs!, "width", "24px")).toBe(true);
    expect(declares(headGlyphs!, "height", "24px")).toBe(true);
    // ⋯ on the title row's end: its glyph box ends on the content edge.
    const tools = ruleFor(".sidekick-journal .sk-day-strip-tools");
    expect(tools, "tools rule").toBeDefined();
    expect(declares(tools!, "grid-area", "tools")).toBe(true);
    expect(declares(tools!, "margin-inline-end", "-12px")).toBe(true);
    // The week row: ‹, the range, › and "Idag" after it, at the start under the title.
    const weekRow = ruleFor(".sidekick-journal .sk-day-strip-weekrow");
    expect(weekRow, "week row rule").toBeDefined();
    expect(declares(weekRow!, "grid-area", "arrows")).toBe(true);
    expect(declares(weekRow!, "justify-self", "start")).toBe(true);
    expect(declares(weekRow!, "display", "flex")).toBe(true);
    expect(declares(weekRow!, "align-items", "center")).toBe(true);
    // The range is the week's meta line between the arrows: nowrap, in the meta type, with the arrows' reach under it.
    const range = ruleFor(".sidekick-journal .journal-day-range");
    expect(range, "range rule").toBeDefined();
    expect(declares(range!, "margin", "0 0 var(--sk-day-week-reach)")).toBe(
      true,
    );
    expect(declares(range!, "white-space", "nowrap")).toBe(true);
    expect(declares(range!, "font", "var(--sk-type-meta)")).toBe(true);
    expect(ruleFor(".sidekick-journal .sk-day-strip-range")).toBeUndefined();
    expect(
      ruleFor(".sidekick-journal .sk-day-strip-weekrow + .sk-day-strip"),
    ).toBeUndefined();
    expect(ruleFor(".sidekick-journal .sk-day-strip-pair")).toBeUndefined();
    // The strip sits right under the head.
    expect(
      declares(ruleFor(".sidekick-journal .sk-day-strip")!, "margin-top", "0"),
    ).toBe(true);
    // The ⋯ panel is a card under the head, its one item 44 high (Work's ⋯ form).
    const panel = ruleFor(".sidekick-journal .journal-more-panel");
    expect(panel, "more panel rule").toBeDefined();
    expect(declares(panel!, "background", "var(--sk-surface)")).toBe(true);
    const item = ruleFor(".sidekick-journal .journal-more-item");
    expect(item, "more item rule").toBeDefined();
    expect(declares(item!, "min-height", "var(--sk-tap)")).toBe(true);
    // The arrows are the family icon buttons: journal.css has no rule of its own for them, only the today state.
    expect(
      ruleFor(".sidekick-journal .sk-day-strip-arrow"),
      "no arrow rule",
    ).toBeUndefined();
    const arrow = ruleFor(
      '.sidekick-journal .sk-day-strip-arrow[aria-disabled="true"]',
    );
    expect(arrow, "aria-disabled arrow rule").toBeDefined();
    // The spent › is --sk-border at full opacity, not 38 % ink.
    expect(declares(arrow!, "color", "var(--sk-border)")).toBe(true);
    expect(declares(arrow!, "opacity", "1")).toBe(true);
    const day = ruleFor(".sidekick-journal .sk-day-strip-day");
    expect(day, "day cell rule").toBeDefined();
    // The day cells have no frame; the selected day is underlined (it used to be a contour).
    expect(declares(day!, "border", "0")).toBe(true);
    const selected = ruleFor(
      '.sidekick-journal .sk-day-strip-day[aria-current="date"]',
    );
    expect(selected, "selected day rule").toBeDefined();
    // The chosen day is drawn as the chosen room: the page colour, a 2 px inset outline in the text
    // colour (--sk-selected-width), the text in --sk-fg. No border, so the cell keeps its size.
    expect(declares(selected!, "background", "var(--sk-nav-active-bg)")).toBe(
      true,
    );
    expect(
      declares(
        selected!,
        "box-shadow",
        "inset 0 0 0 var(--sk-selected-width) var(--sk-nav-active-line)",
      ),
    ).toBe(true);
    expect(declares(selected!, "color", "var(--sk-nav-active-fg)")).toBe(true);
    expect(selected!.declarations).not.toMatch(/inset 0 -2px/);
    expect(selected!.declarations).not.toMatch(/border/);
    const dot = ruleFor(".sidekick-journal .sk-day-strip-dot");
    expect(dot, "dot rule").toBeDefined();
    expect(declares(dot!, "width", "6px")).toBe(true);
    expect(declares(dot!, "border-radius", "50%")).toBe(true);
    expect(
      ruleFor(".sidekick-journal .sk-day-strip-marker"),
      "marker rule",
    ).toBeDefined();
  });

  it("the day view's heading has the type of its level: h2 the title, h3 the section in the foreground colour", () => {
    const h2 = ruleFor(".sidekick-journal h2:not(.sk-card__title)");
    expect(h2, "h2 rule").toBeDefined();
    expect(declares(h2!, "font", "var(--sk-type-title)")).toBe(true);
    const h3 = ruleFor(".sidekick-journal h3");
    expect(h3, "h3 rule").toBeDefined();
    expect(declares(h3!, "font", "var(--sk-type-section)")).toBe(true);
    expect(declares(h3!, "color", "var(--sk-fg)")).toBe(true);
    expect(declares(h3!, "color", "var(--sk-muted)")).toBe(false);
  });

  it("list items and day buttons have no 44 px minimum width", () => {
    const item = ruleFor(".sidekick-journal .sk-day-strip-week > li");
    expect(item ? declares(item, "min-width", "0") : false).toBe(true);
    const day = ruleFor(".sidekick-journal .sk-day-strip-day");
    expect(day ? declares(day, "min-width", "0") : false).toBe(true);
    expect(day?.declarations).not.toMatch(/min-width: 44px/);
    expect(css).not.toMatch(/minmax\(44px/);
  });

  it("the arrows are the family icon buttons, 44 px box and 48 px target, with no inline height", () => {
    const source = read("day-strip.tsx");
    expect(source).toMatch(/className="sk-iconbtn sk-day-strip-arrow"/);
    // No inline size on the arrows: the only inline style in the strip is the day cell's minHeight of 56 px.
    expect(source).not.toMatch(/touchStyle/);
    expect(source.match(/minHeight/g)).toHaveLength(1);
    expect(source).toMatch(/const dayStyle = \{ minHeight: "56px" \};/);
    const family = readSource("features/mcp-apps/ui/family.css");
    expect(family).toMatch(
      /\.sk-iconbtn \{[^}]*width: var\(--sk-tap\);[^}]*height: var\(--sk-tap\);/,
    );
  });
});

describe("Godkänn/Avslå unpressed options read in ink colour with a border ring", () => {
  const unpressed = rules.find(
    (rule) =>
      rule.selector.includes(".journal-check-flat") &&
      rule.selector.includes(':not([aria-pressed="true"])'),
  );

  it("an unpressed option uses --sk-fg text and a --sk-border ring", () => {
    expect(unpressed, "unpressed option rule").toBeDefined();
    expect(declares(unpressed!, "color", "var(--sk-fg)")).toBe(true);
    expect(
      declares(unpressed!, "box-shadow", "inset 0 0 0 1px var(--sk-border)"),
    ).toBe(true);
  });
});

describe("Godkänn/Avslå pair tints the chosen option with its status tone", () => {
  const approve = rules.find(
    (rule) =>
      rule.selector.includes(".journal-check-flat") &&
      rule.selector.includes('[aria-pressed="true"]:nth-child(1)'),
  );
  const decline = rules.find(
    (rule) =>
      rule.selector.includes(".journal-check-flat") &&
      rule.selector.includes('[aria-pressed="true"]:nth-child(2)'),
  );

  it("Godkänn (first option) uses the success tones", () => {
    expect(approve, "pressed Godkänn rule").toBeDefined();
    expect(declares(approve!, "background", "var(--sk-success-bg)")).toBe(true);
    expect(declares(approve!, "color", "var(--sk-success-fg)")).toBe(true);
    expect(
      declares(
        approve!,
        "box-shadow",
        "inset 0 0 0 1px var(--sk-success-line)",
      ),
    ).toBe(true);
  });

  it("Avslå (second option) uses the danger tones, not the page background", () => {
    expect(decline, "pressed Avslå rule").toBeDefined();
    expect(declares(decline!, "background", "var(--sk-danger-bg)")).toBe(true);
    expect(declares(decline!, "color", "var(--sk-danger-fg)")).toBe(true);
    expect(
      declares(decline!, "box-shadow", "inset 0 0 0 1px var(--sk-danger-line)"),
    ).toBe(true);
    expect(declares(decline!, "background", "var(--sk-bg)")).toBe(false);
  });
});

describe("decision bar is sticky only above 400 px", () => {
  // The sticky block is the only @media (min-width: 401px) block; it ends at the column-zero brace.
  const stickyBlock =
    css.match(/@media \(min-width: 401px\) \{([\s\S]*?)\n\}/)?.[1] ?? "";

  it("at 400 px and under the bar is in flow, not sticky", () => {
    const bar = ruleFor(".sidekick-journal .journal-decision-bar");
    expect(bar, "decision bar rule").toBeDefined();
    expect(bar!.declarations).not.toMatch(/position: (sticky|fixed)/);
  });

  it("above 400 px the bar is sticky at the bottom on the card surface", () => {
    expect(stickyBlock, "401 px block").not.toBe("");
    const bar = cssRules(stickyBlock).find(
      (rule) => rule.selector === ".sidekick-journal .journal-decision-bar",
    );
    expect(bar, "sticky decision bar rule").toBeDefined();
    expect(declares(bar!, "position", "sticky")).toBe(true);
    expect(declares(bar!, "bottom", "0")).toBe(true);
    expect(declares(bar!, "background", "var(--sk-surface)")).toBe(true);
  });

  it("no sticky rule for the bar exists outside the 401 px block", () => {
    const outside = css.replace(
      /@media \(min-width: 401px\) \{[\s\S]*?\n\}/,
      "",
    );
    expect(
      cssRules(outside).some(
        (rule) =>
          rule.selector.includes("journal-decision-bar") &&
          /position: sticky/.test(rule.declarations),
      ),
    ).toBe(false);
  });

  it("the review puts the save and reject actions in that bar", () => {
    expect(read("draft-review-parts/decision-bar.tsx")).toContain(
      'className="journal-actions journal-decision-bar"',
    );
  });
});

describe("quiet buttons that lead a line align with the heading", () => {
  it("Tillbaka and Visa originaltext have no side padding", () => {
    for (const selector of [
      ".sidekick-journal .journal-back",
      ".sidekick-journal .journal-toggle",
    ]) {
      const rule = ruleFor(selector);
      expect(rule, `${selector} rule`).toBeDefined();
      expect(declares(rule!, "padding-inline", "0"), selector).toBe(true);
    }
  });

  it("the markup carries the classes the rules target", () => {
    expect(read("journal-view.tsx")).toContain("journal-back sk-btn--quiet");
    expect(read("draft-review-parts/original-text.tsx")).toContain(
      'className="sk-btn--quiet journal-toggle"',
    );
  });
});
