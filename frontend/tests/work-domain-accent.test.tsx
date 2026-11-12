import { render } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { BoardCard } from "@/features/work-app/board-card";
import { HierarchyView } from "@/features/work-app/hierarchy-view";
import { workEn, workSv } from "@/features/work-app/labels";
import {
  domainAccentOf,
  type WorkHierarchyNode,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport";

/*
 * Domain accent (see docs/decisions/log.md D-061). A valid accent name sets data-accent on a Work card or a
 * hierarchy Domain's dot; null and unknown names set nothing. The dot is decorative (aria-hidden).
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000b1";
const NOW = new Date("2026-10-25T12:00:00Z");

function task(domain_accent?: string | null): WorkItemRecord {
  return {
    kind: "task",
    id: TASK_ID,
    title: "Lämna deklarationen",
    status: "todo",
    project_title: "Bokslut och skatt",
    domain_accent,
  };
}

function boardCard(item: WorkItemRecord) {
  const drag = {
    onPointerDown: vi.fn(),
    onPointerMove: vi.fn(),
    onPointerUp: vi.fn(),
    onPointerCancel: vi.fn(),
    onKeyDown: vi.fn(),
  };
  return render(
    <ul>
      <BoardCard
        item={item}
        labels={workSv}
        disabled={false}
        dragging={false}
        onOpen={vi.fn()}
        onMove={vi.fn()}
        drag={drag}
        now={NOW}
      />
    </ul>,
  );
}

describe("domainAccentOf", () => {
  it("keeps the eight names and drops null, missing and unknown values", () => {
    for (const name of [
      "slate",
      "blue",
      "teal",
      "green",
      "amber",
      "orange",
      "rose",
      "violet",
    ]) {
      expect(domainAccentOf(name)).toBe(name);
    }
    expect(domainAccentOf(null)).toBeNull();
    expect(domainAccentOf(undefined)).toBeNull();
    expect(domainAccentOf("neon")).toBeNull();
    expect(domainAccentOf("GREEN")).toBeNull();
  });
});

describe("board card carries the domain accent", () => {
  it("sets data-accent and the accent class for a valid name", () => {
    const { container } = boardCard(task("green"));
    const card = container.querySelector("li.work-card");
    expect(card).toHaveAttribute("data-accent", "green");
    expect(card).toHaveClass("work-accent");
  });

  it("sets no data-accent when the accent is null", () => {
    const { container } = boardCard(task(null));
    const card = container.querySelector("li.work-card");
    expect(card).not.toHaveAttribute("data-accent");
    expect(card).not.toHaveClass("work-accent");
  });

  it("sets no data-accent when the accent is missing", () => {
    const { container } = boardCard(task());
    expect(container.querySelector("li.work-card")).not.toHaveAttribute(
      "data-accent",
    );
  });

  it("treats an unknown name as null", () => {
    const { container } = boardCard(task("neon"));
    const card = container.querySelector("li.work-card");
    expect(card).not.toHaveAttribute("data-accent");
    expect(card).not.toHaveClass("work-accent");
  });

  it("keeps the title and meta line as the text of the card", () => {
    const { container } = boardCard(task("violet"));
    // A Task's kind is not shown on the card; the Project name is the meta line.
    expect(container.querySelector(".work-card-meta")?.textContent).toBe(
      "Bokslut och skatt",
    );
  });
});

describe("hierarchy Domain shows an accent dot", () => {
  const transport = { getProject: vi.fn() } as unknown as WorkTransport;

  function tree(accent: string | null | undefined) {
    const domain: WorkHierarchyNode = {
      kind: "domain",
      id: "019f0000-0000-7000-8000-0000000000h1",
      parent_id: null,
      title: "Ekonomi",
      status: "active",
      version: 1,
      accent,
    };
    return render(
      <HierarchyView
        frame={{ kind: "hierarchy", nodes: [domain], truncated: false }}
        transport={transport}
        labels={workEn}
      />,
    );
  }

  it("draws a hidden dot with data-accent in the Domain heading before a valid accent", () => {
    const { container } = tree("teal");
    const dot = container.querySelector("h3 .hierarchy-accent");
    expect(dot).toHaveAttribute("data-accent", "teal");
    expect(dot).toHaveAttribute("aria-hidden", "true");
    expect(dot?.textContent).toBe("●");
  });

  it("draws no dot when the accent is null", () => {
    const { container } = tree(null);
    expect(container.querySelector(".hierarchy-accent")).toBeNull();
  });

  it("draws no dot when the accent is missing", () => {
    const { container } = tree(undefined);
    expect(container.querySelector(".hierarchy-accent")).toBeNull();
  });

  it("draws no dot for an unknown accent name", () => {
    const { container } = tree("neon");
    expect(container.querySelector(".hierarchy-accent")).toBeNull();
  });
});
