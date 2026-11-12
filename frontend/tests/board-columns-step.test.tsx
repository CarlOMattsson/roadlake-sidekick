import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardCard } from "@/features/work-app/board/board-card";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";

/**
 * A Step on the columns board (Status in a wide frame) shows its square in the card's lead, as a Task shows its ring
 * there, so its title and meta line keep the other cards' x (n10: the meta "Steg" stood indented under a title that
 * started at the card's edge). It is not a control: a Step is not dragged.
 */
const step: WorkItemRecord = {
  kind: "step",
  id: "00000000-0000-4000-8000-000000000006",
  title: "Tell Kerstin afterwards",
  status: "todo",
  version: 1,
  task_id: "00000000-0000-4000-8000-000000000001",
};

function renderCard(layout: "columns" | "single") {
  return render(
    <ul className="work-list">
      <BoardCard
        item={step}
        labels={workEn}
        layout={layout}
        disabled={false}
        dragging={false}
        onOpen={vi.fn()}
        onMove={vi.fn()}
        onToggleDone={vi.fn()}
      />
    </ul>,
  );
}

describe("a Step on the columns board", () => {
  it("has its square in the lead, not a drag handle or a done button", () => {
    const { container } = renderCard("columns");
    const head = container.querySelector(".work-card-head");
    const glyph = head?.querySelector(":scope > .work-card-glyph");
    expect(glyph).not.toBeNull();
    expect(glyph?.querySelector(".sk-status-glyph")).not.toBeNull();
    expect(head?.firstElementChild).toBe(glyph);
    expect(container.querySelector(".work-drag-handle")).toBeNull();
    expect(container.querySelector(".work-card-done")).toBeNull();
    expect(
      screen.getByRole("button", { name: step.title }),
    ).toBeInTheDocument();
  });

  it("keeps the single layout's done button instead of the plain glyph", () => {
    const { container } = renderCard("single");
    expect(container.querySelector(".work-card-glyph")).toBeNull();
    expect(container.querySelector(".work-card-done")).not.toBeNull();
  });
});
