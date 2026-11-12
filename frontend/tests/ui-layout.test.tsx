import { readFileSync } from "node:fs";
import path from "node:path";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppFrame } from "@/features/mcp-apps/ui/layout";

const css = readFileSync(
  path.resolve(import.meta.dirname, "../src/features/mcp-apps/ui/layout.css"),
  "utf8",
);

describe.each(["inline", "full"] as const)("AppFrame mode=%s", (mode) => {
  it("is the frame root with data-mode and the body wrapper around the children", () => {
    const { container } = render(
      <AppFrame mode={mode}>
        <p>Innehåll</p>
      </AppFrame>,
    );

    const root = container.firstElementChild as HTMLElement;
    expect(root).toHaveClass("sk-frame");
    expect(root).toHaveAttribute("data-mode", mode);
    const body = root.firstElementChild as HTMLElement;
    expect(body).toHaveClass("sk-frame__body");
    expect(body).toContainElement(screen.getByText("Innehåll"));
  });
});

describe("layout.css", () => {
  it("makes the frame an inline-size container and names it for @container", () => {
    expect(css).toMatch(
      /\.sk-frame\s*\{[^}]*container-type:\s*inline-size;[^}]*container-name:\s*sk-frame;/,
    );
  });

  it("pads the body with the host safe area on every side", () => {
    for (const side of ["top", "right", "bottom", "left"]) {
      expect(css).toContain(`var(--host-safe-${side}, 0px)`);
    }
  });

  it("uses 0 px inline and 16 px full, and 24 px full from a 640 px container", () => {
    expect(css).toMatch(/--sk-frame-pad:\s*0px;/);
    expect(css).toMatch(
      /\.sk-frame\[data-mode="full"\]\s*>\s*\.sk-frame__body\s*\{[^}]*--sk-frame-pad:\s*16px;/,
    );
    const wide = css.slice(
      css.indexOf("@container sk-frame (min-width: 640px)"),
    );
    expect(wide).toMatch(
      /\.sk-frame\[data-mode="full"\]\s*>\s*\.sk-frame__body\s*\{\s*--sk-frame-pad:\s*24px;/,
    );
  });

  it("switches .sk-wide with a detail to a two-column grid only in a container of at least 640 px", () => {
    const start = css.indexOf(
      "@container sk-frame (min-width: 640px) {\n  .sk-wide",
    );
    expect(start).toBeGreaterThan(-1);
    const wideRule = css.slice(start);
    expect(wideRule).toMatch(/display:\s*grid;/);
    expect(wideRule).toMatch(/grid-template-columns:\s*minmax\(0,\s*2fr\)/);
  });

  it("limits a row title to 3 lines in full screen and to none under a 19rem container", () => {
    expect(css).toMatch(
      /\.sk-frame\[data-mode="full"\] > \.sk-frame__body \{\s*--sk-row-title-lines: 3;\s*\}/,
    );
    expect(css).toMatch(
      /@container sk-frame \(max-width: 18\.99rem\) \{\s*\.sk-frame\[data-mode="full"\] > \.sk-frame__body \{\s*--sk-row-title-lines: none;\s*\}\s*\}/,
    );
  });

  it("uses container queries, not width media queries, and no url()", () => {
    expect(css).not.toMatch(/@media\s*\(\s*(min|max)-width/);
    expect(css).not.toMatch(/url\(/);
  });
});
