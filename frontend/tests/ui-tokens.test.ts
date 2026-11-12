// Design language: the --sk-* tokens in mcp-apps/ui/tokens.css are the only place where Sidekick
// defines its look for MCP app views. Every value reads a host variable first, fallbacks use light-dark(),
// and there is no prefers-color-scheme block, so the host's theme decides light or dark.
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";

const tokensPath = path.resolve(
  import.meta.dirname,
  "../src/features/mcp-apps/ui/tokens.css",
);
const css = readFileSync(tokensPath, "utf8");
const source = css.replace(/\/\*[\s\S]*?\*\//g, "");

// Returns each declaration as [name, value] from the stripped source. Line breaks inside a value are
// collapsed, so a value that prettier wrapped over several lines compares as one line.
function declarations(text: string): Array<[string, string]> {
  return [...text.matchAll(/(--[a-zA-Z0-9-]+)\s*:\s*([^;]+);/g)].map(
    (m): [string, string] => [
      m[1] ?? "",
      (m[2] ?? "")
        .replace(/\s+/g, " ")
        .replace(/\(\s/g, "(")
        .replace(/\s\)/g, ")")
        .trim(),
    ],
  );
}

// Returns every hex colour that is not inside var(...) or light-dark(...). The scan tracks the
// function names it is currently inside, so nested calls such as var(--x, light-dark(#fff, #000)) are fine.
function bareHexColours(text: string): string[] {
  const bare: string[] = [];
  const stack: string[] = [];
  for (const m of text.matchAll(/([a-zA-Z-]*)\(|\)|#[0-9a-fA-F]{3,8}\b/g)) {
    const token = m[0];
    if (token === ")") {
      stack.pop();
    } else if (token.startsWith("#")) {
      if (!stack.some((fn) => fn === "var" || fn === "light-dark"))
        bare.push(token);
    } else {
      stack.push(m[1] ?? "");
    }
  }
  return bare;
}

const values = new Map(declarations(source));

describe("Sidekick design tokens (ui/tokens.css)", () => {
  it("defines the two text sizes and two weights, read from host variables", () => {
    expect(values.get("--sk-text-sm")).toBe(
      "var(--font-text-sm-size, 0.875rem)",
    );
    expect(values.get("--sk-text-md")).toBe("var(--font-text-md-size, 1rem)");
    // The heading sizes were read by no view in the bundle and are gone.
    expect(values.has("--sk-heading-md")).toBe(false);
    expect(values.get("--sk-weight-normal")).toBe(
      "var(--font-weight-normal, 400)",
    );
    expect(values.get("--sk-weight-semibold")).toBe(
      "var(--font-weight-semibold, 600)",
    );
  });

  it("sets the section heading at 18 / 24 in semibold, heavier than the titles it heads", () => {
    expect(values.get("--sk-type-section-size")).toBe("1.125rem");
    expect(values.get("--sk-type-section-line")).toBe("1.5rem");
    expect(values.get("--sk-type-section-weight")).toBe(
      "var(--sk-weight-semibold)",
    );
  });

  it("defines the 4 px spacing scale s1 to s5", () => {
    expect(values.get("--sk-s1")).toBe("4px");
    expect(values.get("--sk-s2")).toBe("8px");
    expect(values.get("--sk-s3")).toBe("12px");
    expect(values.get("--sk-s4")).toBe("16px");
    expect(values.get("--sk-s5")).toBe("24px");
  });

  it("defines the row template: 6 px of air, a 48 minimum, and the section spacing 24 over and 4 under", () => {
    expect(values.get("--sk-row-pad")).toBe("6px");
    expect(values.get("--sk-row-min")).toBe("48px");
    expect(values.get("--sk-section-above")).toBe("var(--sk-s5)");
    expect(values.get("--sk-section-below")).toBe("var(--sk-s1)");
    expect(values.get("--sk-row-title-lines")).toBe("none");
    expect(values.get("--sk-row-air-extra")).toMatch(
      /calc\(\s*\(var\(--sk-row-min\) - var\(--sk-type-row-line\)\) \/ 2 - var\(--sk-row-pad\)\s*\)/,
    );
    expect(values.get("--sk-lead-h")).toBe(
      "calc(2 * var(--sk-row-pad) + var(--sk-type-row-line))",
    );
  });

  it("defines the glyph size, radius and hairline", () => {
    expect(values.get("--sk-glyph")).toBe("16px");
    expect(values.get("--sk-radius")).toBe("var(--border-radius-md, 0.5rem)");
    expect(values.get("--sk-hairline")).toBe(
      "var(--border-width-regular, 1px)",
    );
  });

  it("defines line, background and text for each of the three statuses in use, with host token first", () => {
    // Info was read by no view in the bundle and is gone.
    expect(values.has("--sk-info-bg")).toBe(false);
    for (const status of ["success", "warning", "danger"]) {
      for (const part of ["line", "bg", "fg"]) {
        const value = values.get(`--sk-${status}-${part}`);
        expect(value, `--sk-${status}-${part}`).toBeDefined();
        expect(value, `--sk-${status}-${part}`).toMatch(
          /^var\(--(color-[a-z-]+), light-dark\(#[0-9a-f]{6}, #[0-9a-f]{6}\)\)$/,
        );
      }
    }
  });

  it("marks the active room and day with the page colour, a text-coloured line and a 2 px contour", () => {
    expect(values.get("--sk-nav-active-bg")).toBe("var(--sk-bg)");
    expect(values.get("--sk-nav-active-fg")).toBe("var(--sk-fg)");
    expect(values.get("--sk-nav-active-line")).toBe("var(--sk-fg)");
    expect(values.get("--sk-selected-width")).toBe("2px");
    expect(values.get("--sk-selected-line")).toBe("var(--sk-fg)");
  });

  it("has no tonal tokens, a skeleton mixed from the text colour and the page and the button type steps", () => {
    expect(values.has("--sk-tonal-bg")).toBe(false);
    expect(values.has("--sk-tonal-panel")).toBe(false);
    expect(values.has("--sk-border-on-tonal")).toBe(false);
    expect(source).not.toMatch(/tonal/);
    // The skeleton follows the host's text and page colours (11 % of the text on the page), no tertiary value.
    expect(values.get("--sk-skeleton")).toBe(
      "color-mix(in srgb, var(--sk-fg) 11%, var(--sk-bg))",
    );
    expect(values.get("--sk-skeleton")).not.toMatch(/tertiary/);
    expect(values.has("--sk-panel-line")).toBe(false);
    // The tab row's height: the tap size, never more than 56.
    expect(values.get("--sk-tabs-h")).toBe("min(var(--sk-tap), 56px)");
    expect(values.get("--sk-type-label")).toBe(
      "var(--sk-type-label-weight) var(--sk-type-label-size) / var(--sk-type-label-line) var(--sk-font)",
    );
    expect(values.get("--sk-type-label-size")).toBe("0.875rem");
    expect(values.get("--sk-type-label-line")).toBe("1.125rem");
    expect(values.get("--sk-type-label-weight")).toBe(
      "var(--sk-weight-medium)",
    );
    expect(values.get("--sk-type-button")).toContain(
      "var(--sk-weight-semibold)",
    );
    expect(values.get("--sk-type-label-strong")).toContain(
      "var(--sk-weight-semibold) var(--sk-type-control-size) / var(--sk-type-control-line)",
    );
    expect(values.get("--sk-type-menu")).toContain(
      "var(--sk-weight-medium) var(--sk-type-control-size)",
    );
    expect(values.get("--sk-type-control-size")).toBe("1rem");
    expect(values.get("--sk-type-control-line")).toBe("1.25rem");
    expect(values.get("--sk-check")).toMatch(/^url\("data:image\/svg\+xml/);
  });

  it("has no prefers-color-scheme block", () => {
    expect(source).not.toMatch(/@media\s*\(\s*prefers-color-scheme/);
  });

  it("uses hex colours only inside var(...) or light-dark(...)", () => {
    expect(source).toMatch(/#[0-9a-fA-F]{6}/);
    expect(bareHexColours(source)).toEqual([]);
  });

  it("detects a bare hex colour outside var() or light-dark()", () => {
    expect(bareHexColours("color: #b42318;")).toEqual(["#b42318"]);
    expect(bareHexColours("color: var(--x, #b42318);")).toEqual([]);
    expect(bareHexColours("color: light-dark(#ffffff, #1c1c1e);")).toEqual([]);
  });
});
