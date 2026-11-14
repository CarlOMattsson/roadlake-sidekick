import { render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  AgendaSummary,
  InlineSummary,
  type InlineSummaryData,
} from "@/features/work-app/inline/inline-summary";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";

/*
 * A Task marked done ("completed") has no overdue state: its due date is not shown as "Försenad" or
 * "Overdue" in red, on the inline Task summary or on an agenda row. Open Tasks keep the overdue text.
 */

/** Fixed clock (25 Oct 2026, Europe/Stockholm): a due date of 23 Oct is two days overdue. */
beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-10-25T12:00:00Z"));
});

afterEach(() => {
  vi.useRealTimers();
});

const doneTask: InlineSummaryData = {
  kind: "task",
  title: "Ring Anna om offerten",
  status: "completed",
  dueDate: "2026-10-23",
  version: 4,
};

describe("a done Task's due date on the inline summary", () => {
  it("shows no overdue text and no red tone for a completed Task", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={doneTask}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Overdue/)).toBeNull();
    expect(container.querySelector('[data-tone="overdue"]')).toBeNull();
  });

  it("shows no 'Försenad' text in Swedish for a completed Task", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={doneTask}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Försenad/)).toBeNull();
    expect(container.querySelector('[data-tone="overdue"]')).toBeNull();
  });

  it("shows no due part at all for a completed Task, even when the date is later", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{ ...doneTask, dueDate: "2026-10-30" }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(/Förfaller/)).toBeNull();
    expect(screen.queryByText(/Försenad/)).toBeNull();
  });

  it("keeps the overdue text for an open Task with the same date", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...doneTask, status: "in_progress" }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Overdue since Fri 23 Oct")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    expect(container.querySelector('[data-tone="overdue"]')).not.toBeNull();
  });
});

describe("a done Task's due date on an agenda row", () => {
  const doneRow: WorkItemRecord = {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a1",
    title: "Betala faktura",
    status: "completed",
    due_at: "2026-10-20T09:00:00Z",
    agenda_group: "overdue",
  };

  it("shows no overdue text for a row whose Task is done", () => {
    render(
      <AgendaSummary
        page={{ items: [doneRow], next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    const row = screen
      .getByRole("button", { name: "Betala faktura" })
      .closest("li");
    expect(row).not.toBeNull();
    // A done Task's row has no due words at all: no due line and no tone.
    expect(row?.querySelector(".work-compact-row-due")).toBeNull();
    expect(row?.querySelector("[data-tone]")).toBeNull();
    expect(row?.textContent).not.toMatch(/Overdue/);
  });
});
