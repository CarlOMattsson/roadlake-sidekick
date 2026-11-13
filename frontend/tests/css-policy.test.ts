// Policies on the MCP apps' stylesheets that are rules about the source, not about how a view looks, so they read the
// CSS files as text on purpose (the same kind of test as no-swedish-comments and css-prefix-policy):
//   1. The host decides light or dark: no prefers-color-scheme media query, and a fixed hex colour only as the
//      fallback inside var() or light-dark().
//   2. Every var(--sk-*) is defined in tokens.css or in the stylesheet that reads it.
//   3. A file with a transition or an animation switches both off under prefers-reduced-motion.
//   4. font-size is never given in px outside a var() fallback.
//   5. A rule for a button that sets min-height reaches 44 px.
//   6. Inline-mode rules never scroll on the y axis.
//   7. The palette has the eight accent lines and no other accent token; a status token reads a host variable first.
//   8. The tonal button level is gone, and a selected state is drawn with the 2 px contour token.
// How the views look (sizes, colours, spacing) is measured in a browser by the specs under tests/e2e.
import path from "node:path";
import { describe, expect, it } from "vitest";

import {
  customPropertyDeclarations,
  customPropertyUses,
  cssRules,
  declarationsOf,
  lineOf,
  loadCssFiles,
  readCss,
} from "./helpers/css-contract";
import { readText, sourceFiles, srcDir } from "./helpers/source-files";

// The shared MCP-app kit, its room shell and the four rooms, with their subfolders.
const scannedDirs = [
  "mcp-apps",
  "work-app",
  "journal-app",
  "shopping-app",
  "control-app",
];
const files = scannedDirs.flatMap(loadCssFiles);
// The shell's own stylesheet sets some variables from script (--sk-bar-h), so the token and rule checks cover the kit
// (mcp-apps/ui) and the rooms, not the shell.
const ruleFiles = files.filter(
  (file) =>
    !file.rel.startsWith("mcp-apps/") || file.rel.startsWith("mcp-apps/ui/"),
);

/** Every hex colour in `text` that is not inside a var(...) or light-dark(...) call, however deeply nested. */
function bareHexColours(text: string): string[] {
  const bare: string[] = [];
  const stack: string[] = [];
  for (const m of text.matchAll(/([a-zA-Z-]*)\(|\)|#[0-9a-fA-F]{3,8}\b/g)) {
    const token = m[0];
    if (token === ")") stack.pop();
    else if (token.startsWith("#")) {
      if (!stack.some((fn) => fn === "var" || fn === "light-dark"))
        bare.push(token);
    } else stack.push(m[1] ?? "");
  }
  return bare;
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
// Drawn under 44 on purpose, with a 48 target from an ::after that the browser specs measure
// (layout-mcp-app.spec.ts, via effectiveTargetSize): the compact button and the chip are 40, the row menu's ×, the
// inline card's link row and the journal card's linked-contact chip are listed by name, never by pattern.
const compactTonal = /\.sk-btn--compact(?![\w-])|\.sk-chip(?![\w-])/;
const compactText = /\.work-agenda-menu-close(?![\w-])/;
const afterTargetButton =
  /\.work-compact-card\s*>\s*\.work-compact-action\.sk-btn--open(?![\w-])|\.journal-card-links\s+button\.journal-link-name(?![\w-])/;
// A row title and the Status ring have min-height 0 on purpose: their 48 target is the ::after over the row.
const rowTargetButton =
  /\.work-agenda-body\s*>\s*button(?![\w-])|\.work-card-head\s*>\s*button/;

// Selector applies to the inline mode: [data-mode="inline"] or a class with inline, card or summary in its name.
const inlineSelector =
  /\[data-mode="inline"\]|\.[\w-]*(?:inline|card|summary)[\w-]*/i;

// Minimum touch target: 2.75rem or 44px, or one of the touch tokens alone or with a length added on top.
function meetsTouchTarget(value: string): boolean {
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

describe("stylesheets leave light or dark to the host", () => {
  it("scans the expected stylesheets", () => {
    const names = files.map((file) => file.rel);
    for (const expected of [
      "mcp-apps/ui/tokens.css",
      "mcp-apps/ui/states.css",
      "work-app/shell/work.css",
      "work-app/tasks/task-detail.css",
      "work-app/inline/inline-summary.css",
      "journal-app/journal.css",
      "shopping-app/shopping.css",
      "control-app/control.css",
    ])
      expect(names).toContain(expected);
  });

  it("no stylesheet uses a prefers-color-scheme media query", () => {
    const hits = files.flatMap((file) =>
      [...file.css.matchAll(/@media\s*\(\s*prefers-color-scheme/g)].map(
        (match) => `${file.rel}:${lineOf(file.css, match.index ?? 0)}`,
      ),
    );
    expect(hits).toEqual([]);
  });

  it("a fixed hex colour appears only inside var(...) or light-dark(...)", () => {
    const violations = files
      .map((file) => ({ file: file.rel, hex: bareHexColours(file.css) }))
      .filter(({ hex }) => hex.length > 0)
      .map(({ file, hex }) => `${file}: ${hex.join(", ")}`);
    expect(violations).toEqual([]);
  });

  it("finds a bare hex colour outside var() or light-dark()", () => {
    expect(bareHexColours("color: #b42318;")).toEqual(["#b42318"]);
    expect(bareHexColours("color: var(--x, #b42318);")).toEqual([]);
    expect(bareHexColours("color: light-dark(#ffffff, #1c1c1e);")).toEqual([]);
    expect(
      bareHexColours("color-mix(in oklab, var(--x, #fff) 14%, #000)"),
    ).toEqual(["#000"]);
  });
});

describe("stylesheet rules", () => {
  it("every --sk-* read in a stylesheet is defined in tokens.css or in that same stylesheet", () => {
    const tokens = files.find((file) => file.rel === "mcp-apps/ui/tokens.css");
    expect(tokens).toBeDefined();
    const shared = customPropertyDeclarations(tokens?.css ?? "");
    const violations: string[] = [];
    for (const file of ruleFiles) {
      // A component may declare its own tokens (for example --sk-cb-* in counts-bar.css), but only in the stylesheet
      // that reads them, so no file depends on another file's local token.
      const local = customPropertyDeclarations(file.css);
      for (const name of customPropertyUses(file.css)) {
        if (!shared.has(name) && !local.has(name))
          violations.push(`${file.rel} reads ${name}, which is not defined`);
      }
    }
    expect(violations).toEqual([]);
  });

  it("every file with transition or animation has a prefers-reduced-motion: reduce block that turns it off", () => {
    const violations: string[] = [];
    for (const file of ruleFiles) {
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
        const off = blocks.some((body) =>
          cssRules(body).some((rule) =>
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
    for (const file of ruleFiles) {
      for (const rule of cssRules(file.css)) {
        for (const declaration of declarationsOf(rule.body)) {
          if (
            declaration.property !== "font-size" &&
            declaration.property !== "font"
          )
            continue;
          const withoutVar = declaration.value.replace(/var\([^()]*\)/g, "");
          if (/\d(?:\.\d+)?px\b/.test(withoutVar))
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} { ${declaration.property}: ${declaration.value} }`,
            );
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("button rules with min-height reach 2.75rem or 44px", () => {
    const violations: string[] = [];
    for (const file of ruleFiles) {
      for (const rule of cssRules(file.css)) {
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
          if (declaration.value === "0" && rowTargetButton.test(rule.selector))
            continue;
          if (!meetsTouchTarget(declaration.value))
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} min-height: ${declaration.value}`,
            );
        }
      }
    }
    expect(violations).toEqual([]);
  });

  it("inline-mode rules never scroll on the y axis", () => {
    const violations: string[] = [];
    for (const file of ruleFiles) {
      for (const rule of cssRules(file.css)) {
        if (!inlineSelector.test(rule.selector)) continue;
        for (const declaration of declarationsOf(rule.body)) {
          if (
            !["overflow", "overflow-y", "overflow-block"].includes(
              declaration.property,
            )
          )
            continue;
          if (/\b(?:auto|scroll)\b/.test(declaration.value))
            violations.push(
              `${file.rel}:${rule.line} ${rule.selector} { ${declaration.property}: ${declaration.value} }`,
            );
        }
      }
    }
    expect(violations).toEqual([]);
  });
});

describe("the design tokens", () => {
  const tokens = readCss("mcp-apps/ui/tokens.css").replace(/\s+/g, " ");
  const names = [...tokens.matchAll(/(--[a-zA-Z0-9-]+)\s*:/g)].map(
    (match) => match[1] ?? "",
  );

  it("defines the eight accent lines and no other accent token", () => {
    expect(
      names.filter((name) => name.startsWith("--sk-accent-")).sort(),
    ).toEqual(
      ["slate", "blue", "teal", "green", "amber", "orange", "rose", "violet"]
        .map((accent) => `--sk-accent-${accent}-line`)
        .sort(),
    );
  });

  it("gives each status a line, a background and a text colour that read a host colour variable first", () => {
    for (const status of ["success", "warning", "danger"])
      for (const part of ["line", "bg", "fg"]) {
        const declaration = new RegExp(
          `--sk-${status}-${part}:\\s*var\\(\\s*--color-[a-z-]+,\\s*light-dark\\(`,
        );
        expect(tokens, `--sk-${status}-${part}`).toMatch(declaration);
      }
  });

  it("the progress bar reads host text colours first", () => {
    const progress = readCss("mcp-apps/ui/progress.css").replace(/\s+/g, " ");
    expect(progress).toMatch(/var\(\s*--color-text-secondary,\s*light-dark\(/);
    expect(progress).toMatch(/var\(\s*--color-text-info,\s*light-dark\(/);
  });

  it("has no tonal tokens", () => {
    expect(tokens).not.toMatch(/tonal/);
  });
});

describe("retired design", () => {
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
    for (const file of sourceFiles(srcDir, /\.(tsx?|css)$/)) {
      const text = readText(file);
      for (const pattern of stale)
        if (pattern.test(text))
          violations.push(`${path.relative(srcDir, file)} ${pattern}`);
    }
    expect(violations).toEqual([]);
  });

  it("a selected state is drawn from the 2 px contour token, never as a bare 1 px ring in the selected line", () => {
    const users = files.filter((file) =>
      file.css.includes("var(--sk-selected-width"),
    );
    expect(users.map((file) => file.rel)).toEqual(
      expect.arrayContaining([
        "mcp-apps/ui/family.css",
        "mcp-apps/ui/segmented.css",
      ]),
    );
    const oneOnly = files.filter((file) =>
      /inset 0 0 0 1px var\(--sk-selected-line/.test(file.css),
    );
    expect(oneOnly.map((file) => file.rel)).toEqual([]);
  });
});
