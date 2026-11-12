// CSS contract for the MCP apps' design language (docs/reference/design-system.md). The test
// reads the CSS source files as text and changes no CSS. Five rules:
//   1. A file that uses transition or animation has an @media (prefers-reduced-motion: reduce)
//      block that turns off exactly those properties.
//   2. font-size (and the font shorthand) is never given in px, except as a fallback inside var(…, …px).
//   3. A rule whose selector targets a button (button, or a class ending in -btn, -button,
//      -lead, -open or -back) and that sets min-height has at least 2.75rem or 44px.
//   4. No overflow-y: auto or scroll in selectors that apply to the inline mode.
//   5. Every var(--sk-*) is defined in tokens.css or in the same stylesheet.
import { readdirSync, readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const featuresDir = path.resolve(import.meta.dirname, "../src/features");

// Directories whose top-level *.css files are scanned: the shared MCP-app kit and the three apps.
// Shopping has its single stylesheet at shopping-app/*.css, found by the same glob as the others.
const scannedDirs = [
  "mcp-apps/ui",
  "work-app",
  "journal-app",
  "shopping-app",
  "control-app",
];

type CssFile = { rel: string; css: string };

// Comments are blanked out, keeping newlines, so line numbers in messages stay correct and words
// inside a comment cannot trip a rule.
function stripComments(raw: string): string {
  return raw.replace(/\/\*[\s\S]*?\*\//g, (match) =>
    match.replace(/[^\n]/g, " "),
  );
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

function loadCss(): CssFile[] {
  return scannedDirs.flatMap((dir) => {
    const absolute = path.join(featuresDir, dir);
    return readdirSync(absolute)
      .filter((entry) => entry.endsWith(".css"))
      .sort()
      .map((entry) => ({
        rel: `${dir}/${entry}`,
        css: stripComments(readFileSync(path.join(absolute, entry), "utf8")),
      }));
  });
}

type Rule = { selector: string; body: string; line: number };
type Declaration = { property: string; value: string };

// Flat rules. Nested rules inside @media are matched on their own, because a rule body never
// contains braces. At-rule preludes are never followed by a body without braces, so they do not match.
function rulesOf(css: string): Rule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)]
    .map((match) => ({
      selector: (match[1] ?? "").trim(),
      body: match[2] ?? "",
      line: lineOf(css, match.index ?? 0),
    }))
    .filter((rule) => !rule.selector.startsWith("@"));
}

function declarationsOf(body: string): Declaration[] {
  return body
    .split(";")
    .map((part) => {
      const colon = part.indexOf(":");
      if (colon === -1) return null;
      return {
        property: part.slice(0, colon).trim().toLowerCase(),
        value: part.slice(colon + 1).trim(),
      };
    })
    .filter((declaration): declaration is Declaration => declaration !== null);
}

// Bodies of every @media (prefers-reduced-motion: reduce) block in the file.
function reducedMotionBodies(css: string): string[] {
  const opener = /@media\s*\(\s*prefers-reduced-motion\s*:\s*reduce\s*\)\s*\{/g;
  return [...css.matchAll(opener)].map((match) => {
    const start = (match.index ?? 0) + match[0].length;
    let depth = 1;
    let i = start;
    for (; i < css.length && depth > 0; i++) {
      if (css[i] === "{") depth++;
      else if (css[i] === "}") depth--;
    }
    return css.slice(start, i - 1);
  });
}

// Selector targets a button: the element itself, or a class ending in -btn, -button, -lead, -open or -back.
const buttonElement = /(?:^|[\s>+~,(])button(?![\w-])/;
const buttonClass = /\.[\w-]*(?:-btn|-button|-lead|-open|-back)(?![\w-])/;
// The compact button and the chip are 40 high on purpose. Their 48 target is
// checked by their own tests below, which read the ::after that extends them, so the touch-target rule still holds.
const compactTonal = /\.sk-btn--compact(?![\w-])|\.sk-chip(?![\w-])/;
// The row menu's × is an icon button with no min-height of its own; its ::after extends the
// target. Its own test below reads that ::after.
const compactText = /\.work-agenda-menu-close(?![\w-])/;
// A row title and the Status ring have min-height 0 on purpose. Their 48 target is the ::after over the row
// (`.work-agenda-line` or `li.work-card`, min-height 48px) or over the ring's column, so they are exempt from the
// min-height rule; the row test below checks that those rows hold 48.
const rowTargetButton =
  /\.work-agenda-body\s*>\s*button(?![\w-])|\.work-card-head\s*>\s*button/;

// Visible under 44 on purpose, with a 48 target from an ::after. Each selector is listed by name,
// never by pattern, and the test "an ::after-target button reaches 48" below reads its ::after, so the 48 rule holds:
//  - the inline card's link row ("Öppna Agenda · 3 fler ›"): a compact text row, 40 drawn (--sk-compact);
//  - the journal card's linked-contact chip: 32 drawn (the meta line's chip), min-height 0 to let the 32 stand.
const afterTargetButton =
  /\.work-compact-card\s*>\s*\.work-compact-action\.sk-btn--open(?![\w-])|\.journal-card-links\s+button\.journal-link-name(?![\w-])/;

// Selector applies to the inline mode: [data-mode="inline"] or a class with inline, card or summary in its name.
const inlineSelector =
  /\[data-mode="inline"\]|\.[\w-]*(?:inline|card|summary)[\w-]*/i;

// Minimum touch target: 2.75rem or 44px. Anything else (including var() without a literal) is rejected.
function meetsTouchTarget(value: string): boolean {
  // The touch tokens (tokens.css: --sk-tap 44, --sk-tap-lg 48, --sk-row-min 48), alone or with a
  // length added on top.
  if (
    /^(?:var\(--sk-(?:tap(?:-lg)?|row-min)\)|calc\(var\(--sk-(?:tap(?:-lg)?|row-min)\) \+ [^)]*\)\)?)$/.test(
      value.trim(),
    )
  )
    return true;
  const match = /^(\d*\.?\d+)(rem|px)$/.exec(value.trim());
  if (!match) return false;
  const size = Number(match[1]);
  return match[2] === "rem" ? size >= 2.75 : size >= 44;
}

// Custom property declarations (`--sk-name:`) and reads (`var(--sk-name`) in a stylesheet.
const customPropertyDeclaration = /(?<![\w-])(--sk-[\w-]+)\s*:/g;
const customPropertyUse = /var\(\s*(--sk-[\w-]+)/g;

function customPropertyNames(css: string, pattern: RegExp): Set<string> {
  return new Set([...css.matchAll(pattern)].map((match) => match[1] ?? ""));
}

const files = loadCss();

// Body of the top-level rule that lists this selector (whitespace-normalised; the whole list or one part of it, so a
// selector shared with another shape, e.g. the card foot, still holds) in one stylesheet. Fails the test when the rule
// is missing, so a renamed selector cannot pass silently.
function ruleBody(rel: string, selector: string): string {
  const file = files.find((entry) => entry.rel === rel);
  expect(file, rel).toBeDefined();
  const rule = rulesOf(file?.css ?? "").find((candidate) => {
    const whole = candidate.selector.replace(/\s+/g, " ");
    return (
      whole === selector ||
      whole.split(",").some((part) => part.trim() === selector)
    );
  });
  expect(rule, `${rel} ${selector}`).toBeDefined();
  return rule?.body ?? "";
}

function valueOf(body: string, property: string): string | undefined {
  return declarationsOf(body).find(
    (declaration) => declaration.property === property,
  )?.value;
}

describe("MCP-app UI CSS contract (D28)", () => {
  it("scans the expected stylesheets", () => {
    const names = files.map((file) => file.rel);
    expect(names).toContain("mcp-apps/ui/states.css");
    expect(names).toContain("work-app/work.css");
    expect(names).toContain("work-app/task-detail.css");
    expect(names).toContain("work-app/inline-summary.css");
    expect(names).toContain("journal-app/journal.css");
    expect(names).toContain("shopping-app/shopping.css");
  });

  it("every --sk-* read in a stylesheet is defined in tokens.css or in that same stylesheet", () => {
    const tokens = files.find((file) => file.rel === "mcp-apps/ui/tokens.css");
    expect(tokens).toBeDefined();
    const shared = customPropertyNames(
      tokens?.css ?? "",
      customPropertyDeclaration,
    );
    const violations: string[] = [];
    for (const file of files) {
      // A component may declare its own tokens (for example --sk-cb-* in counts-bar.css), but only
      // in the stylesheet that reads them, so no file depends on another file's local token.
      const local = customPropertyNames(file.css, customPropertyDeclaration);
      for (const name of customPropertyNames(file.css, customPropertyUse)) {
        if (!shared.has(name) && !local.has(name)) {
          violations.push(`${file.rel} reads ${name}, which is not defined`);
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("every file with transition or animation has a prefers-reduced-motion: reduce block that turns it off", () => {
    const violations: string[] = [];
    for (const file of files) {
      const motion = ["transition", "animation"].filter((property) =>
        new RegExp(`(?<![\\w-])${property}\\s*:`).test(file.css),
      );
      if (motion.length === 0) continue;
      const blocks = reducedMotionBodies(file.css);
      if (blocks.length === 0) {
        violations.push(
          `${file.rel} uses ${motion.join("/")} without @media (prefers-reduced-motion: reduce)`,
        );
        continue;
      }
      for (const property of motion) {
        // The block holds nested rules, so each rule's declarations are read on their own.
        const off = blocks.some((body) =>
          rulesOf(body).some((rule) =>
            declarationsOf(rule.body).some(
              (declaration) =>
                declaration.property === property &&
                declaration.value === "none",
            ),
          ),
        );
        if (!off)
          violations.push(
            `${file.rel}: reduced-motion block does not set ${property}: none`,
          );
      }
    }
    expect(violations).toEqual([]);
  });

  it("font-size is never set in px outside a var() fallback", () => {
    const violations: string[] = [];
    for (const file of files) {
      for (const rule of rulesOf(file.css)) {
        for (const declaration of declarationsOf(rule.body)) {
          if (
            declaration.property !== "font-size" &&
            declaration.property !== "font"
          )
            continue;
          const withoutVar = declaration.value.replace(/var\([^()]*\)/g, "");
          if (/\d(?:\.\d+)?px\b/.test(withoutVar)) {
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} { ${declaration.property}: ${declaration.value} }`,
            );
          }
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("button rules with min-height reach 2.75rem or 44px", () => {
    const violations: string[] = [];
    for (const file of files) {
      for (const rule of rulesOf(file.css)) {
        const selectors = rule.selector.split(",").map((part) => part.trim());
        const isButton = selectors.some(
          (part) => buttonElement.test(part) || buttonClass.test(part),
        );
        if (!isButton) continue;
        if (
          selectors.some(
            (part) =>
              compactTonal.test(part) ||
              compactText.test(part) ||
              afterTargetButton.test(part),
          )
        )
          continue;
        for (const declaration of declarationsOf(rule.body)) {
          if (declaration.property !== "min-height") continue;
          // Min-height 0 on a row title or a Status button is the row's own target (see rowTargetButton).
          if (declaration.value === "0" && rowTargetButton.test(rule.selector))
            continue;
          if (!meetsTouchTarget(declaration.value)) {
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} min-height: ${declaration.value}`,
            );
          }
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("a chosen chip has the 2 px outline in the text colour, the selected fill and a tick", () => {
    const pressed = ruleBody(
      "mcp-apps/ui/family.css",
      ':is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button.sk-chip[aria-pressed="true"], .sk-chip[aria-pressed="true"]',
    );
    expect(valueOf(pressed, "border-color")).toBe("var(--sk-selected-line)");
    expect(valueOf(pressed, "background")).toBe("var(--sk-selected-bg)");
    // The 1 px edge plus (2 - 1) px inside it is the 2 px contour (--sk-selected-width), so nothing moves.
    expect(valueOf(pressed, "box-shadow")?.replace(/\s+/g, " ")).toBe(
      "inset 0 0 0 calc(var(--sk-selected-width) - var(--sk-hairline)) var(--sk-selected-line)",
    );
    expect(valueOf(pressed, "font-weight")).toBe("var(--sk-weight-semibold)");
    const tick = ruleBody(
      "mcp-apps/ui/family.css",
      '.sk-chip[aria-pressed="true"]::before',
    );
    expect(valueOf(tick, "-webkit-mask")).toContain("var(--sk-check)");
  });

  it("the four button levels are drawn as the design says: ink, outline, bare text, red text without fill or edge", () => {
    const base =
      ":is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control)";
    const secondary = ruleBody(
      "mcp-apps/ui/family.css",
      `${base} button.sk-btn--secondary, .sk-btn--secondary`,
    );
    expect(valueOf(secondary, "background")).toBe("transparent");
    expect(valueOf(secondary, "border-color")).toBe("var(--sk-border)");
    const quiet = ruleBody(
      "mcp-apps/ui/family.css",
      `${base} button.sk-btn--quiet, .sk-btn--quiet`,
    );
    expect(valueOf(quiet, "background")).toBe("transparent");
    expect(valueOf(quiet, "border-color")).toBe("transparent");
    expect(valueOf(quiet, "color")).toBe("var(--sk-fg)");
    // Destructive: red text, no fill and no edge.
    const danger = ruleBody(
      "mcp-apps/ui/family.css",
      `${base} button.sk-btn--danger, .sk-btn--danger`,
    );
    expect(valueOf(danger, "color")).toBe("var(--sk-overdue-fg)");
    expect(valueOf(danger, "background")).toBe("transparent");
    expect(valueOf(danger, "border-color")).toBe("transparent");
    expect(valueOf(danger, "box-shadow")).toBeUndefined();
  });

  it("the tonal button level is gone: no .sk-btn--tonal, .work-text-btn or .control-action and no tonal tokens in any stylesheet or view", () => {
    const stale = [
      /\.sk-btn--tonal/,
      /\.work-text-btn/,
      /\.control-action(?![\w-])/,
      /--sk-tonal-bg/,
      /--sk-tonal-panel/,
      /--sk-border-on-tonal/,
    ];
    const violations: string[] = [];
    for (const file of files) {
      for (const pattern of stale) {
        if (pattern.test(file.css)) violations.push(`${file.rel} ${pattern}`);
      }
    }
    const srcDir = path.resolve(import.meta.dirname, "../src");
    const walk = (dir: string): string[] =>
      readdirSync(dir, { withFileTypes: true }).flatMap((entry) =>
        entry.isDirectory()
          ? walk(path.join(dir, entry.name))
          : /\.(tsx?|css)$/.test(entry.name)
            ? [path.join(dir, entry.name)]
            : [],
      );
    for (const file of walk(srcDir)) {
      const text = readFileSync(file, "utf8");
      for (const pattern of stale) {
        if (pattern.test(text))
          violations.push(`${path.relative(srcDir, file)} ${pattern}`);
      }
    }
    expect(violations).toEqual([]);
  });

  it("the room, the day and the chip that are chosen are marked with a 2 px contour, not a fill alone", () => {
    const tokens = readFileSync(
      path.join(featuresDir, "mcp-apps/ui/tokens.css"),
      "utf8",
    );
    expect(tokens).toMatch(/--sk-selected-width:\s*2px/);
    // The selected contour is drawn from that token wherever a selection is shown.
    const users = files.filter((file) =>
      file.css.includes("var(--sk-selected-width"),
    );
    expect(users.map((file) => file.rel)).toEqual(
      expect.arrayContaining([
        "mcp-apps/ui/family.css",
        "mcp-apps/ui/segmented.css",
      ]),
    );
    // No selection in the stylesheets is a bare 1 px inset ring in the selected line.
    const oneOnly = files.filter((file) =>
      /inset 0 0 0 1px var\(--sk-selected-line/.test(file.css),
    );
    expect(oneOnly.map((file) => file.rel)).toEqual([]);
  });

  it("the chosen room is drawn with the page colour and the 2 px contour, and the round + is ink", () => {
    const shell = readFileSync(
      path.join(featuresDir, "mcp-apps/sidekick-shell.css"),
      "utf8",
    );
    const room = rulesOf(shell.replace(/\/\*[\s\S]*?\*\//g, "")).find(
      (rule) =>
        rule.selector.replace(/\s+/g, " ") ===
        '.sk-rooms .sk-rooms__tab[aria-current="page"]',
    );
    expect(room, "chosen room rule").toBeDefined();
    expect(valueOf(room?.body ?? "", "background")).toBe(
      "var(--sk-nav-active-bg)",
    );
    expect(valueOf(room?.body ?? "", "box-shadow")).toBe(
      "inset 0 0 0 var(--sk-selected-width) var(--sk-nav-active-line)",
    );
    const plus = ruleBody(
      "mcp-apps/ui/family.css",
      ":is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button.sk-iconbtn--primary, .sk-iconbtn--primary",
    );
    expect(valueOf(plus, "border-radius")).toBe("50%");
    expect(valueOf(plus, "background")).toBe(
      "var(--sk-inverse-bg) content-box",
    );
    expect(valueOf(plus, "color")).toBe("var(--sk-inverse-fg)");
    // The ink disc is 32 (--sk-plus) in the 44 box: beside the search and ⋯ glyphs, not a button of its own size.
    expect(valueOf(plus, "padding")).toBe(
      "calc((var(--sk-tap) - var(--sk-plus)) / 2)",
    );
    const tokens = files.find((file) => file.rel === "mcp-apps/ui/tokens.css");
    expect(tokens?.css).toMatch(/--sk-plus:\s*2rem;/);
    // The focus ring of a room lies inside its cell, so the strip's edge never cuts it.
    const ring = rulesOf(shell.replace(/\/\*[\s\S]*?\*\//g, "")).find(
      (rule) =>
        rule.selector.replace(/\s+/g, " ") ===
        ".sk-rooms :is(.sk-rooms__tab, .sk-pick):focus-visible",
    );
    expect(valueOf(ring?.body ?? "", "outline-offset")).toBe("-2px");
  });

  it("Kontroll's title is a visible h2 under the Back row, not the old screen-reader heading", () => {
    const title = ruleBody(
      "control-app/control.css",
      ".sk-rooms__pane .sidekick-control .control-title",
    );
    expect(valueOf(title, "font")).toBe("var(--sk-type-title)");
    expect(valueOf(title, "color")).toBe("var(--sk-fg)");
    // 4 under the Back row's box (gives back the pane's gap), not out of the flow as the old screen-reader heading.
    expect(valueOf(title, "margin")).toBe("calc(-1 * var(--sk-s1)) 0 0");
    expect(valueOf(title, "position")).toBeUndefined();
    const control = files.find(
      (file) => file.rel === "control-app/control.css",
    );
    expect(control?.css).not.toMatch(/sk-back-header--heading/);
    const family = files.find(
      (file) => file.rel === "mcp-apps/ui/back-header.css",
    );
    expect(family?.css ?? "").not.toMatch(/sk-back-header--heading/);
  });

  it("the rows that hold a row title's or a Status ring's 48 target are at least 48 high, from the one row token --sk-row-min", () => {
    // The shared Contact row and the Kontroll row read the token, and tokens.css defines it as 48.
    expect(
      valueOf(ruleBody("mcp-apps/ui/row.css", ".sk-row"), "min-height"),
    ).toBe("var(--sk-row-min)");
    expect(
      valueOf(
        ruleBody("control-app/control.css", ".sidekick-control .control-row"),
        "min-height",
      ),
    ).toBe("var(--sk-row-min)");
    // The Status card row (single layout): its title and ring are covered by the row's ::after.
    expect(
      valueOf(
        ruleBody(
          "work-app/work.css",
          '.sidekick-work .work-board[data-layout="single"] .work-list > li.work-card',
        ),
        "min-height",
      ),
    ).toBe("var(--sk-row-min)");
    expect(
      valueOf(ruleBody("mcp-apps/ui/tokens.css", ":root"), "--sk-row-min"),
    ).toBe("48px");
  });

  it("inline-mode rules never scroll on the y axis", () => {
    const violations: string[] = [];
    for (const file of files) {
      for (const rule of rulesOf(file.css)) {
        if (!inlineSelector.test(rule.selector)) continue;
        for (const declaration of declarationsOf(rule.body)) {
          if (
            !["overflow", "overflow-y", "overflow-block"].includes(
              declaration.property,
            )
          )
            continue;
          if (/\b(?:auto|scroll)\b/.test(declaration.value)) {
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} { ${declaration.property}: ${declaration.value} }`,
            );
          }
        }
      }
    }
    expect(violations).toEqual([]);
  });

  // Journal and Shopping follow the Work card rules (work.css is the reference).
  it("the app name in Journal and Shopping is a small overline, not a large heading", () => {
    // Every app's name is the family eyebrow (sk-eyebrow, family.css): small, normal weight, no uppercase.
    const eyebrow = ruleBody("mcp-apps/ui/family.css", ".sk-eyebrow");
    expect(valueOf(eyebrow, "font-size")).toBe("var(--sk-type-meta-size)");
    expect(valueOf(eyebrow, "text-transform")).toBe("none");
  });

  it("the Shopping inline card grows with its content: height is auto, not a fixed height", () => {
    const body = ruleBody("shopping-app/shopping.css", ".shopping-card-body");
    expect(valueOf(body, "height")).toBe("auto");
  });

  it("primary actions in Journal and Shopping are filled with the host inverse colour, as in Work", () => {
    // Journal's primary action is the family's sk-btn--primary (family.css), filled with the inverse pair.
    const family = ruleBody(
      "mcp-apps/ui/family.css",
      ':is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button[type="submit"], :is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button.sk-btn--primary, .sk-btn--primary',
    );
    expect(valueOf(family, "background")).toBe("var(--sk-inverse-bg)");
    expect(valueOf(family, "font")).toBe("var(--sk-type-label-strong)");
  });
});
