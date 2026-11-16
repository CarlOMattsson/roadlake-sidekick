import { render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { aiLabelsFor } from "@/features/work-app/ai/ai-labels";
import { aiMarkOf } from "@/features/work-app/ai/ai-task-mark";
import { BoardSummary } from "@/features/work-app/board/board-summary";
import { AgendaSummary } from "@/features/work-app/inline/inline-summary";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkBoardPage,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import { transport } from "@tests/helpers/work-app-fixtures";

// The AI mark on the rows of the Agenda and Status, full and inline: "AI" while a Task is marked as possible with AI,
// "AI ✓" once its AI plan is approved, each read aloud in the app's language. Rendered with a fake transport, not in a
// real Claude or Android host.

const due = "2026-10-20T09:00:00Z";
const possible: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Sammanfatta offerten",
  status: "todo",
  due_at: due,
  agenda_group: "overdue",
  ai_possible: true,
};
const approved: WorkItemRecord = {
  ...possible,
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Researcha leverantörer",
  status: "in_progress",
  ai_plan_approved: true,
};
const plain: WorkItemRecord = {
  ...possible,
  id: "019f0000-0000-7000-8000-0000000000a3",
  title: "Ring Anna",
  ai_possible: false,
};
const items = [possible, approved, plain];
const board: WorkBoardPage = {
  columns: {
    todo: [possible, plain],
    in_progress: [approved],
    blocked: [],
    completed: [],
  },
  next_cursor: null,
};

describe("aiMarkOf", () => {
  it("is approved once the plan is approved, possible while only marked, and none otherwise", () => {
    expect(aiMarkOf(approved)).toBe("approved");
    expect(aiMarkOf(possible)).toBe("possible");
    expect(aiMarkOf(plain)).toBeUndefined();
    expect(aiMarkOf({ ai_possible: true })).toBe("possible");
  });

  it("marks no done or cancelled Task, and no Project", () => {
    expect(aiMarkOf({ ...possible, status: "completed" })).toBeUndefined();
    expect(aiMarkOf({ ...approved, status: "cancelled" })).toBeUndefined();
    expect(
      aiMarkOf({ ...possible, kind: "project", status: "active" }),
    ).toBeUndefined();
  });
});

describe.each([
  ["English", workEn, inlineSummaryLabelsEn],
  ["Swedish", workSv, inlineSummaryLabelsSv],
] as const)("the AI mark on list rows (%s)", (_name, labels, inline) => {
  const a = aiLabelsFor(labels.dateLocale);

  /** The marks inside the row whose title is `title`: the row is the nearest list item. */
  function marksOf(title: string) {
    const row = screen
      .getAllByText(title)
      .map((node) => node.closest("li"))
      .find(Boolean)!;
    return within(row).queryAllByRole("img", {
      name: new RegExp(`^(${a.possible}|${a.planApproved})$`),
    });
  }
  function expectMarks() {
    const [mark] = marksOf(possible.title);
    expect(mark).toHaveAccessibleName(a.possible);
    expect(mark).toHaveTextContent(/^AI$/);
    const [done] = marksOf(approved.title);
    expect(done).toHaveAccessibleName(a.planApproved);
    expect(done).toHaveTextContent(/^AI ✓$/);
    expect(marksOf(plain.title)).toEqual([]);
  }

  it("marks the Agenda's rows", () => {
    render(
      <WorkView
        transport={transport()}
        initial={{
          kind: "agenda",
          filters: {},
          page: { items, next_cursor: null },
        }}
        labels={labels}
      />,
    );
    expectMarks();
  });

  it("marks the cards of Status", () => {
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "board", filters: {}, page: board }}
        labels={labels}
      />,
    );
    expectMarks();
  });

  it("marks the inline agenda's rows, and the row's name says it", () => {
    render(
      <AgendaSummary
        page={{ items, next_cursor: null }}
        labels={inline}
        onOpen={vi.fn()}
      />,
    );
    expectMarks();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`^${approved.title}, .*${a.planApproved}$`),
      }),
    ).toBeInTheDocument();
  });

  it("marks the inline Status card's rows", () => {
    render(<BoardSummary page={board} labels={labels} onOpen={vi.fn()} />);
    expectMarks();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`^${possible.title}, .*${a.possible}$`),
      }),
    ).toBeInTheDocument();
  });
});
