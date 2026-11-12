// D-061 (see docs/decisions/log.md): eight named accent colours in mcp-apps/ui/tokens.css. Each name has
// only its edge (-line), which switches with the theme through light-dark(); -bg, -fg and -base were read by no
// view and were removed (gzip size). The test reads the CSS file as text and changes no CSS. The contrast
// requirements (3:1 for an edge, 4.5:1 for text) are computed against the fallback values by a separate script
// and are not tested here.
import { describe, expect, it } from "vitest";

import { readSource } from "./helpers/source-files";

const css = readSource("features/mcp-apps/ui/tokens.css");
const source = css.replace(/\/\*[\s\S]*?\*\//g, "");

const accentNames = [
  "slate",
  "blue",
  "teal",
  "green",
  "amber",
  "orange",
  "rose",
  "violet",
] as const;

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
// function names it is currently inside, so nested calls such as color-mix(in oklab, var(--x) 14%, ...) are checked too.
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

describe("accent palette tokens (D-061, ui/tokens.css)", () => {
  it("defines a line for each of the eight accent names, from light-dark()", () => {
    for (const name of accentNames) {
      const token = `--sk-accent-${name}-line`;
      expect(values.get(token), token).toMatch(
        /^light-dark\(#[0-9a-f]{6}, #[0-9a-f]{6}\)$/,
      );
    }
    expect(accentNames).toHaveLength(8);
  });

  it("defines no accent token outside the eight lines", () => {
    const accentTokens = [...values.keys()].filter((key) =>
      key.startsWith("--sk-accent-"),
    );
    const allowed = new Set(
      accentNames.map((name) => `--sk-accent-${name}-line`),
    );
    expect(accentTokens.filter((key) => !allowed.has(key))).toEqual([]);
  });

  it("uses hex colours only inside var(...) or light-dark(...)", () => {
    expect(source).toMatch(/#[0-9a-fA-F]{6}/);
    expect(bareHexColours(source)).toEqual([]);
  });
});
