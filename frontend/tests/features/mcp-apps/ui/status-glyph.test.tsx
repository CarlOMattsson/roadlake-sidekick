import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  StatusGlyph,
  type StatusGlyphKind,
} from "@/features/mcp-apps/ui/status-glyph";

describe.each<{ kind: StatusGlyphKind; status: string; glyph: string }>([
  { kind: "task", status: "todo", glyph: "ring-empty" },
  { kind: "task", status: "in_progress", glyph: "ring-empty" },
  { kind: "task", status: "blocked", glyph: "ring-empty" },
  { kind: "task", status: "completed", glyph: "ring-check" },
  { kind: "project", status: "active", glyph: "ring-empty" },
  { kind: "project", status: "paused", glyph: "ring-dashed" },
  { kind: "project", status: "completed", glyph: "ring-filled" },
  { kind: "step", status: "todo", glyph: "square-empty" },
  { kind: "step", status: "in_progress", glyph: "square-empty" },
  { kind: "step", status: "blocked", glyph: "square-empty" },
  { kind: "step", status: "completed", glyph: "square-check" },
  { kind: "task", status: "waiting_for_review", glyph: "ring-dashed" },
  { kind: "project", status: "archived", glyph: "ring-dashed" },
  { kind: "step", status: "open", glyph: "square-dashed" },
])("StatusGlyph ($kind $status)", ({ kind, status, glyph }) => {
  it("draws the shape for its status", () => {
    const { container } = render(<StatusGlyph kind={kind} status={status} />);

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("data-glyph", glyph);
    expect(svg).toHaveClass("sk-status-glyph");
    expect(svg).toHaveAttribute("viewBox", "0 0 16 16");
  });
});

describe("StatusGlyph accessibility", () => {
  it("is a labelled image when a label is given", () => {
    render(<StatusGlyph kind="task" status="in_progress" label="Pågår" />);

    const image = screen.getByRole("img", { name: "Pågår" });
    expect(image).not.toHaveAttribute("aria-hidden");
  });

  it("is hidden from assistive technology without a label", () => {
    const { container } = render(
      <StatusGlyph kind="task" status="completed" />,
    );

    const svg = container.querySelector("svg");
    expect(svg).toHaveAttribute("aria-hidden", "true");
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
  });
});

describe("StatusGlyph shape rules", () => {
  it("shows only done or not done: Klar is a ticked ring, every open status an empty one", () => {
    const glyphs = ["todo", "in_progress", "blocked", "completed"].map(
      (status) => {
        const { container, unmount } = render(
          <StatusGlyph kind="task" status={status} />,
        );
        const glyph = container
          .querySelector("svg")
          ?.getAttribute("data-glyph");
        unmount();
        return glyph;
      },
    );

    expect(glyphs).toEqual([
      "ring-empty",
      "ring-empty",
      "ring-empty",
      "ring-check",
    ]);
  });

  it("uses a square frame for steps and never a ring", () => {
    const { container } = render(
      <StatusGlyph kind="step" status="completed" />,
    );

    expect(
      container.querySelector("rect.sk-status-glyph__frame"),
    ).not.toBeNull();
    expect(container.querySelector("circle")).toBeNull();
  });

  it("keeps colour out of inline presentation attributes", () => {
    const { container } = render(
      <StatusGlyph kind="project" status="completed" label="Klart" />,
    );

    const painted = container.querySelectorAll("[fill], [stroke], [color]");
    expect(painted).toHaveLength(0);
  });
});
