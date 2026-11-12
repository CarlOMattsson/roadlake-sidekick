// CSS contract for the host theme. MCP apps inherit the host's colours and background, so every
// app stylesheet must be transparent, follow the host tokens and use light-dark() instead of a
// media query. The test reads the CSS source files; it changes no CSS.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

import { sourceFiles } from "./helpers/source-files";

const featuresDir = path.resolve(import.meta.dirname, "../src/features");

// Feature folders whose CSS is scanned. mcp-apps/ui is the shared kit and has no app root.
const scannedDirs = [
  "work-app",
  "journal-app",
  "shopping-app",
  "control-app",
  "mcp-apps",
];

// The three app roots. Each root element carries the class in its TSX (work-view.tsx,
// journal-view.tsx, shopping-view.tsx). hierarchy.css has no root of its own; the hierarchy
// view renders inside `.sidekick-work`, so it is covered by the work root.
const apps = [
  { name: "work", dir: "work-app", root: ".sidekick-work" },
  { name: "journal", dir: "journal-app", root: ".sidekick-journal" },
  { name: "shopping", dir: "shopping-app", root: ".sidekick-shopping" },
  { name: "control", dir: "control-app", root: ".sidekick-control" },
] as const;

type CssFile = { rel: string; css: string; raw: string };

// Comments are blanked out, keeping newlines, so line numbers in messages stay correct and
// words such as "prefers-color-scheme block" inside a comment cannot trip a rule.
function stripComments(raw: string): string {
  return raw.replace(/\/\*[\s\S]*?\*\//g, (match) =>
    match.replace(/[^\n]/g, " "),
  );
}

function lineOf(text: string, index: number): number {
  return text.slice(0, index).split("\n").length;
}

function loadCss(dirName: string): CssFile[] {
  return sourceFiles(path.join(featuresDir, dirName), /\.css$/).map((file) => {
    const raw = readFileSync(file, "utf8");
    return {
      rel: path.relative(featuresDir, file).split(path.sep).join("/"),
      raw,
      css: stripComments(raw),
    };
  });
}

const allFiles = scannedDirs.flatMap(loadCss);

// Returns the declarations of the rule whose selector is exactly `selector` (e.g. `.sidekick-work`).
// `.sidekick-work h1 {` does not match, because the selector must be followed directly by `{`.
function rootBlock(css: string, selector: string): string | null {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`(?<![\\w.-])${escaped}\\s*\\{([^}]*)\\}`).exec(css);
  return match?.[1] ?? null;
}

// Values of every declaration with the given property name, including multi-line shorthands.
function declarationValues(block: string, property: RegExp): string[] {
  return [
    ...block.matchAll(
      new RegExp(`(?:^|[\\s;])(${property.source})\\s*:([^;]*);`, "g"),
    ),
  ].map((match) => (match[2] ?? "").trim());
}

// True when the hex colour at `index` sits inside var(…) or light-dark(…), which is the only
// place a fixed colour may appear. Walks back to the nearest unclosed "(" and checks its name.
function hexIsAllowed(css: string, index: number): boolean {
  let depth = 0;
  for (let i = index - 1; i >= 0; i--) {
    const ch = css[i];
    if (ch === ")") depth++;
    else if (ch === "(") {
      if (depth === 0) {
        const name = /([a-zA-Z-]+)$/.exec(css.slice(0, i))?.[1] ?? "";
        return name === "var" || name === "light-dark";
      }
      depth--;
    }
  }
  return false;
}

describe("app CSS contract for host theming", () => {
  it.each(apps)(
    "$name root background is transparent or none",
    ({ root, dir }) => {
      const file = loadCss(dir).find((f) => rootBlock(f.css, root) !== null);
      expect(file, `${root} root rule not found in ${dir}`).toBeDefined();
      const block = rootBlock(file!.css, root) ?? "";
      const values = declarationValues(block, /background/);
      expect(
        values.length,
        `${file!.rel}: ${root} has no background declaration`,
      ).toBeGreaterThan(0);
      for (const value of values) {
        expect(
          ["transparent", "none"],
          `${file!.rel}: ${root} background is "${value}"`,
        ).toContain(value);
      }
    },
  );

  it("no CSS file uses @media (prefers-color-scheme", () => {
    const hits = allFiles.flatMap((f) => {
      const matches = [
        ...f.css.matchAll(/@media\s*\(\s*prefers-color-scheme/g),
      ];
      return matches.map((m) => `${f.rel}:${lineOf(f.css, m.index ?? 0)}`);
    });
    expect(
      hits,
      `prefers-color-scheme media query in: ${hits.join(", ")}`,
    ).toEqual([]);
  });

  it("fixed hex colours appear only inside var(…, #hex) or light-dark(", () => {
    const violations = allFiles.flatMap((f) =>
      [...f.css.matchAll(/#[0-9a-fA-F]{3,8}\b/g)]
        .filter((m) => !hexIsAllowed(f.css, m.index ?? 0))
        .map((m) => `${f.rel}:${lineOf(f.css, m.index ?? 0)} ${m[0]}`),
    );
    expect(
      violations,
      `hex colour outside var()/light-dark(): ${violations.join(", ")}`,
    ).toEqual([]);
  });

  it.each(apps)("$name app has a :focus-visible style", ({ dir, name }) => {
    const files = loadCss(dir);
    const hasFocusVisible = files.some((f) => f.css.includes(":focus-visible"));
    expect(hasFocusVisible, `${name} app has no :focus-visible rule`).toBe(
      true,
    );
  });

  it.each(apps)(
    "$name root padding uses --host-safe- insets",
    ({ root, dir }) => {
      const file = loadCss(dir).find((f) => rootBlock(f.css, root) !== null);
      expect(file, `${root} root rule not found in ${dir}`).toBeDefined();
      const block = rootBlock(file!.css, root) ?? "";
      const values = declarationValues(
        block,
        /padding(?:-(?:top|right|bottom|left))?/,
      );
      expect(
        values.length,
        `${file!.rel}: ${root} has no padding declaration`,
      ).toBeGreaterThan(0);
      for (const value of values) {
        expect(
          value,
          `${file!.rel}: ${root} padding does not reference --host-safe-`,
        ).toContain("--host-safe-");
      }
    },
  );
});

// every inline Work card (task, project, contact, agenda, board, hierarchy, confirmation) shares one
// frame and one card-type line. Reads the rules of the Work stylesheets (work.css, task-detail.css and
// inline-summary.css, where the inline cards' rules now live); it changes no CSS.
type CssRule = { selectors: string; declarations: string };

function cssRules(css: string): CssRule[] {
  return [...css.matchAll(/([^{}]+)\{([^{}]*)\}/g)].map((match) => ({
    selectors: (match[1] ?? "").replace(/\s+/g, " ").trim(),
    declarations: (match[2] ?? "").replace(/\s+/g, " ").trim(),
  }));
}

// True when the rule declares exactly `property: value` (one declaration, normalised spacing).
function declares(rule: CssRule, property: string, value: string): boolean {
  return rule.declarations
    .split(";")
    .some((declaration) => declaration.trim() === `${property}: ${value}`);
}

const workSheets = [
  "work-app/shell/work.css",
  "work-app/tasks/task-detail.css",
  "work-app/inline/inline-summary.css",
].map((rel) => allFiles.find((f) => f.rel === rel));
const workRules = workSheets.flatMap((sheet) =>
  sheet ? cssRules(sheet.css) : [],
);

describe("Work inline cards share one frame", () => {
  it("the Work stylesheets are loaded", () => {
    expect(workSheets, "work-app stylesheets").not.toContain(undefined);
  });

  it("one rule gives every inline card and the board summary the same frame", () => {
    // The frame is the family's sk-card (family.css); work.css declares no surface of its own.
    const ownSurface = workRules.filter(
      (rule) =>
        (rule.selectors.includes("work-compact-card") ||
          rule.selectors.includes("section[aria-label]")) &&
        declares(rule, "background", "var(--work-surface)"),
    );
    expect(ownSurface.map((rule) => rule.selectors)).toEqual([]);
    const family = cssRules(
      readFileSync(
        path.resolve(
          import.meta.dirname,
          "../src/features/mcp-apps/ui/family.css",
        ),
        "utf8",
      ).replace(/\/\*[\s\S]*?\*\//g, ""),
    ).find((rule) => rule.selectors === ".sk-card");
    expect(family, ".sk-card rule").toBeDefined();
    expect(declares(family!, "background", "var(--sk-surface)")).toBe(true);
    expect(
      declares(family!, "border", "var(--sk-hairline) solid var(--sk-line)"),
    ).toBe(true);
    // Cards are 12 (designsystem §2): the card radius token, not the 8 of buttons and fields.
    expect(declares(family!, "border-radius", "var(--sk-radius-card)")).toBe(
      true,
    );
    expect(family?.declarations, "frame uses no fixed hex").not.toMatch(
      /#[0-9a-fA-F]{3,8}\b/,
    );
  });

  it("the card type is the family's sk-eyebrow; the board heading takes the same look", () => {
    const heading = workRules.find((rule) =>
      rule.selectors.includes("h2.sk-eyebrow"),
    );
    expect(heading, "board heading eyebrow rule").toBeDefined();
    expect(heading ? declares(heading, "margin", "0") : false).toBe(true);
    expect(
      heading ? declares(heading, "font-size", "var(--sk-text-sm)") : false,
    ).toBe(true);
  });

  it("the app name is visible as the eyebrow inline; only the work-visually-hidden h1 is clipped", () => {
    // The family's one hidden-text rule (family.css) holds every room's hidden class.
    const family = allFiles.find((f) => f.rel === "mcp-apps/ui/family.css");
    const hidden = (family ? cssRules(family.css) : []).find((rule) =>
      rule.selectors.includes(".work-visually-hidden"),
    );
    expect(hidden, "hidden heading rule").toBeDefined();
    expect(hidden ? declares(hidden, "clip-path", "inset(50%)") : false).toBe(
      true,
    );
    expect(
      hidden?.selectors,
      "the header h1 is no longer hidden",
    ).not.toContain("> header > h1");
  });

  it("an error inside a card is the family's error box: no work.css rule cancels its frame", () => {
    const nested = workRules.find((rule) =>
      rule.selectors.includes('[role="alert"]'),
    );
    expect(nested, "no work.css alert rule").toBeUndefined();
  });
});
