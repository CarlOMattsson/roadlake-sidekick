import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { ownerDayPlus } from "@/features/mcp-apps/ui/due";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  InlineSummary,
  type InlineSummaryData,
} from "@/features/work-app/inline/inline-summary";
import { installFixedClock } from "@tests/helpers/inline-summary-fixtures";

installFixedClock();

const task: InlineSummaryData = {
  kind: "task",
  title: "Ring Anna om offerten",
  status: "in_progress",
  dueDate: "2026-10-30T09:00:00Z",
  datapoints: {
    steps: { done: 2, total: 5 },
    contacts: 1,
  },
};

const project: InlineSummaryData = {
  kind: "project",
  title: "Sommarfest",
  status: "active",
  dueDate: "2026-11-15",
  datapoints: { contacts: 4 },
};

describe("InlineSummary ready state", () => {
  it("renders the title as text, not as markup", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, title: "<img src=x> Ring Anna" }}
      />,
    );
    expect(screen.getByText("<img src=x> Ring Anna")).toBeInTheDocument();
    expect(container.querySelector("img")).toBeNull();
  });

  it("shows the translated status in a chip", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={task}
      />,
    );
    const chip = container.querySelector(".work-chip");
    expect(chip).toHaveTextContent("Pågår");
  });

  it("draws no ring in front of an open status, so the chip does not read as a radio button", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
      />,
    );
    expect(container.querySelector(".work-chip")).toHaveTextContent(
      "In progress",
    );
    expect(container.querySelector(".work-chip svg")).toBeNull();
  });

  it("draws the check beside a done status, hidden from assistive technology", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, status: "completed" }}
      />,
    );
    const glyph = container.querySelector(".work-chip svg");
    expect(glyph).toHaveAttribute("data-glyph", "ring-check");
    expect(glyph).toHaveAttribute("aria-hidden", "true");
  });

  it("shows an unknown status as it arrived, with the dashed glyph", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...project, status: "archived" }}
      />,
    );
    expect(container.querySelector(".work-chip")).toHaveTextContent("archived");
    expect(container.querySelector(".work-chip svg")).toHaveAttribute(
      "data-glyph",
      "ring-dashed",
    );
  });

  it("shows the relative due date for an instant and for a calendar date", () => {
    const { rerender } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
      />,
    );
    expect(screen.getByText("Due Fri 30 Oct")).toBeInTheDocument();

    rerender(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={project}
      />,
    );
    // A Project's date is its target, not a due date.
    expect(screen.getByText("Target date: 15 Nov")).toBeInTheDocument();
    expect(screen.queryByText(/^Due:/)).not.toBeInTheDocument();
  });

  it("shows the due date in Swedish with the Swedish labels", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={task}
      />,
    );
    expect(screen.getByText("Klart senast fre 30 okt")).toBeInTheDocument();
  });

  it("names an overdue date 'Overdue since' and marks its tone for the host", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, dueDate: "2026-10-23" }}
      />,
    );
    expect(screen.getByText("Overdue since Fri 23 Oct")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
  });

  it("omits the due part when there is no due date", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, dueDate: null }}
      />,
    );
    expect(screen.queryByText(/^Due:/)).not.toBeInTheDocument();
  });

  it("puts steps as a progress count and contacts in the meta line", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
      />,
    );
    expect(screen.getByText("2 of 5 steps")).toBeInTheDocument();
    expect(container.querySelector(".sk-progress")).toHaveTextContent(
      "2 of 5 steps",
    );
    expect(screen.getByText("Contacts: 1").closest("p")).toHaveTextContent(
      "Due Fri 30 Oct · Contacts: 1",
    );
    expect(container.querySelector("ul, li")).toBeNull();
  });

  it("shows at most three datapoints even if more are passed", () => {
    const extra = {
      ...task,
      datapoints: {
        steps: { done: 1, total: 2 },
        tasks: { done: 1, total: 4 },
        overdue: 2,
        contacts: 1,
        more: 9,
      },
    } as InlineSummaryData;
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={extra}
      />,
    );
    expect(container.querySelector(".sk-progress")).toHaveTextContent(
      "1 of 2 steps",
    );
    expect(screen.getByText("2 overdue").closest("p")).toHaveTextContent(
      "Due Fri 30 Oct · 1 of 4 tasks done · 2 overdue",
    );
    expect(container.textContent).not.toContain("Contacts: 1");
    expect(container.textContent).not.toContain("more");
  });

  it("shows no progress when no steps are given, and no datapoints when none are given", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...project, datapoints: undefined }}
      />,
    );
    expect(container.querySelector(".sk-progress")).toBeNull();
    expect(screen.queryByText(/^Contacts:/)).not.toBeInTheDocument();
    expect(screen.getByText("Target date: 15 Nov")).toBeInTheDocument();
  });

  it("offers at most two actions, Done beside Open task, each a 44 px button", async () => {
    const onOpen = vi.fn();
    const onComplete = vi.fn();
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
        onOpen={onOpen}
        onComplete={onComplete}
      />,
    );
    const buttons = screen.getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Mark as done",
      "Open task",
    ]);
    // Done is the primary action and Open task the open text button with ›, side by side in one row.
    expect(buttons[0]).toHaveClass("sk-btn--primary");
    expect(buttons[1]).toHaveClass("sk-btn--open");
    expect(buttons[1]?.querySelector("svg")).not.toBeNull();
    expect(buttons[0]?.parentElement).toBe(buttons[1]?.parentElement);
    // The 44 px minimum is the family stylesheet's (measured in work-inline-styles-mcp-app.spec.ts), not an inline style.
    for (const button of buttons) {
      expect(button).not.toHaveAttribute("style");
      expect(button).toHaveClass("work-compact-action");
    }

    await userEvent.click(screen.getByRole("button", { name: "Mark as done" }));
    await userEvent.click(screen.getByRole("button", { name: "Open task" }));
    expect(onComplete).toHaveBeenCalledTimes(1);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("makes Open the open text button, not ink, when there is no Done", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, status: "completed" }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("button", { name: "Open task" })).toHaveClass(
      "sk-btn--open",
    );
  });

  it("names the task button for what it does, in both languages, with or without Done", () => {
    for (const [labels, text] of [
      [inlineSummaryLabelsSv, "Öppna uppgiften"],
      [inlineSummaryLabelsEn, "Open task"],
    ] as const) {
      const { unmount } = render(
        <InlineSummary
          state="ready"
          labels={labels}
          summary={task}
          onOpen={vi.fn()}
          onComplete={vi.fn()}
        />,
      );
      expect(screen.getByRole("button", { name: text })).toHaveClass(
        "sk-btn--open",
      );
      expect(screen.queryByText(/Visa mer|Show more/)).toBeNull();
      unmount();
    }
  });

  it("shows no Update button: a stale record is read again from the notice", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Update" })).toBeNull();
    expect(screen.getAllByRole("button")).toHaveLength(1);
  });

  it("shows the Task's priority, project and one line of description, cut with an ellipsis", () => {
    const longText = `Ring Anna om offerten. ${"Det här är ett långt stycke. ".repeat(6)}`;
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{
          ...task,
          priority: "high",
          projectTitle: "Kök",
          description: longText,
        }}
        onOpen={vi.fn()}
        onComplete={vi.fn()}
      />,
    );
    expect(screen.getByText("Kök · Prioritet: Hög")).toBeInTheDocument();
    const description = document.querySelector(".work-compact-description");
    expect(description?.textContent?.endsWith("…")).toBe(true);
    expect(description?.textContent?.length).toBeLessThanOrEqual(80);
    expect(description?.textContent).not.toContain("\n");
  });

  it("names the priority level: 'Priority: Urgent'", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, priority: "urgent" }}
      />,
    );
    expect(screen.getByText("Priority: Urgent")).toBeInTheDocument();
  });

  it("shows no priority word for a normal priority and no description line when it is blank", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, priority: "normal", description: "   " }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(/High/)).toBeNull();
    expect(container.querySelector(".work-compact-description")).toBeNull();
  });

  it("shows a Project's target and its Task progress and overdue count in the meta line", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{
          ...project,
          dueDate: "2026-12-15",
          datapoints: { tasks: { done: 3, total: 12 }, overdue: 2 },
        }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Måldatum: 15 dec").closest("p")).toHaveTextContent(
      "Måldatum: 15 dec · 3 av 12 uppgifter klara · 2 försenade",
    );
  });

  it("writes a Project's target day in lower case after the colon", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{ ...project, dueDate: ownerDayPlus(new Date(), 1) }}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Måldatum: imorgon")).toBeInTheDocument();
  });

  it("leaves the overdue part out when no Task is overdue, and keeps the Tasks count", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{
          ...project,
          datapoints: { tasks: { done: 0, total: 3 }, overdue: 0 },
        }}
      />,
    );
    expect(screen.getByText("0 of 3 tasks done")).toBeInTheDocument();
    expect(screen.queryByText("0 overdue")).toBeNull();
  });

  it("renders no action it was not given", () => {
    render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
      />,
    );
    expect(screen.queryAllByRole("button")).toHaveLength(0);
  });

  it("has no menus, popovers or inner scroll", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
        onOpen={vi.fn()}
      />,
    );
    expect(
      container.querySelector(
        '[role="menu"], [role="menuitem"], [role="listbox"], [role="combobox"], [role="dialog"], select',
      ),
    ).toBeNull();
    expect(container.querySelector("[style*='overflow']")).toBeNull();
  });
});

describe("InlineSummary other states", () => {
  it("shows loading as a busy status with no actions", () => {
    const { container } = render(
      <InlineSummary state="loading" labels={inlineSummaryLabelsEn} />,
    );
    expect(container.querySelector("section")).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.getByRole("status")).toHaveTextContent("Loading…");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the empty text with no actions", () => {
    render(<InlineSummary state="empty" labels={inlineSummaryLabelsSv} />);
    expect(screen.getByText("Inget att visa.")).toBeInTheDocument();
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("shows the shared error with Försök igen when a retry is given", async () => {
    const onRetry = vi.fn();
    render(
      <InlineSummary
        state="error"
        labels={inlineSummaryLabelsSv}
        kindLabel={inlineSummaryLabelsSv.kind.task}
        subject="work:task"
        cause={new Error("offline")}
        onRetry={onRetry}
      />,
    );
    // What could not be read, then what the failure says: the same read error as every room.
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Uppgiften kunde inte hämtas",
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Sidekick svarade inte.",
    );
    expect(
      screen.getByText(inlineSummaryLabelsSv.kind.task),
    ).toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Försök igen" }));
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it("shows the shared error without a retry button when none is given", () => {
    render(
      <InlineSummary
        state="error"
        labels={inlineSummaryLabelsEn}
        kindLabel={inlineSummaryLabelsEn.kind.project}
        subject="work:project"
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load the project",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
