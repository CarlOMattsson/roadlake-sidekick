import { cleanup, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { AppFrame } from "@/features/mcp-apps/ui/layout";

import { readStylesheet } from "./helpers/stylesheet";

const css = readStylesheet("features/mcp-apps/ui/layout.css");

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
  const WIDE = "@container sk-frame (min-width: 640px)";
  const NARROW = "@container sk-frame (max-width: 18.99rem)";

  function renderFrame(mode: "inline" | "full", detail = false) {
    const { container } = render(
      <AppFrame mode={mode}>
        <div className="sk-wide">
          <p>Lista</p>
          {detail ? <p>Detalj</p> : null}
        </div>
      </AppFrame>,
    );
    const root = container.firstElementChild as HTMLElement;
    return { root, body: root.firstElementChild as HTMLElement };
  }

  it("makes the frame an inline-size container and names it for @container", () => {
    const { root } = renderFrame("inline");

    expect(css.styleOf(root)).toMatchObject({
      "container-type": "inline-size",
      "container-name": "sk-frame",
    });
  });

  it("pads the body with the host safe area on every side", () => {
    const values = css.rules.flatMap((rule) =>
      Object.values(rule.declarations),
    );
    for (const side of ["top", "right", "bottom", "left"]) {
      expect(values.join(" ")).toContain(`var(--host-safe-${side}, 0px)`);
    }
  });

  it("uses 0 px inline and 16 px full, and 24 px full from a 640 px container", () => {
    const inline = renderFrame("inline").body;
    expect(css.styleOf(inline)["--sk-frame-pad"]).toBe("0px");
    cleanup();

    const full = renderFrame("full").body;
    expect(css.styleOf(full)["--sk-frame-pad"]).toBe("16px");
    expect(css.styleOf(full, { conditions: [WIDE] })["--sk-frame-pad"]).toBe(
      "24px",
    );
  });

  it("switches .sk-wide with a detail to a two-column grid only in a container of at least 640 px", () => {
    const { body } = renderFrame("full", true);
    const wide = body.querySelector(".sk-wide") as Element;

    const grid = css.styleOf(wide, { conditions: [WIDE] });
    expect(grid.display).toBe("grid");
    expect(grid["grid-template-columns"]).toMatch(/^minmax\(0, 2fr\)/);
    expect(css.styleOf(wide).display).not.toBe("grid");
  });

  it("limits a row title to 3 lines in full screen and to none under a 19rem container", () => {
    const { body } = renderFrame("full");

    expect(css.styleOf(body)["--sk-row-title-lines"]).toBe("3");
    expect(
      css.styleOf(body, { conditions: [NARROW] })["--sk-row-title-lines"],
    ).toBe("none");
  });

  it("uses container queries, not width media queries, and no url()", () => {
    const conditions = css.rules.flatMap((rule) => rule.conditions);
    expect(conditions.filter((text) => text.startsWith("@media"))).toEqual([]);
    expect(
      css.rules.flatMap((rule) => Object.values(rule.declarations)).join(" "),
    ).not.toContain("url(");
  });
});
