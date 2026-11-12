import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  InlineSummary,
  type InlineSummaryData,
} from "@/features/work-app/inline/inline-summary";
import { installFixedClock } from "./helpers/inline-summary-fixtures";
import { readStylesheet } from "./helpers/stylesheet";

installFixedClock();

const task: InlineSummaryData = {
  kind: "task",
  title: "Ring Anna om offerten",
  status: "in_progress",
  dueDate: "2026-10-30T09:00:00Z",
  datapoints: {
    steps: { done: 2, total: 5 },
    contacts: 1,
    subtasks: 3,
  },
};

const project: InlineSummaryData = {
  kind: "project",
  title: "Sommarfest",
  status: "active",
  dueDate: "2026-11-15",
  datapoints: { contacts: 4, subtasks: 12 },
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

  it("draws the status glyph beside the chip text, hidden from assistive technology", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={task}
      />,
    );
    const glyph = container.querySelector(".work-chip svg");
    expect(glyph).toHaveAttribute("data-glyph", "ring-empty");
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
    expect(screen.getByText("Target: 15 Nov")).toBeInTheDocument();
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
    expect(screen.getByText("Förfaller fre 30 okt")).toBeInTheDocument();
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

  it("puts steps as a progress count and contacts and subtasks in the meta line, in order", () => {
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
      "Due Fri 30 Oct · Contacts: 1 · Subtasks: 3",
    );
    expect(container.querySelector("ul, li")).toBeNull();
  });

  it("shows at most three datapoints even if more are passed", () => {
    const extra = {
      ...task,
      datapoints: {
        steps: { done: 1, total: 2 },
        contacts: 1,
        subtasks: 1,
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
    expect(screen.getByText("Contacts: 1").closest("p")).toHaveTextContent(
      "Due Fri 30 Oct · Contacts: 1 · Subtasks: 1",
    );
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
    expect(screen.queryByText(/^Subtasks:/)).not.toBeInTheDocument();
    expect(screen.getByText("Target: 15 Nov")).toBeInTheDocument();
  });

  it("offers at most two actions, Done beside Show more, each a 44 px button", async () => {
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
      "Done",
      "Show more",
    ]);
    // Done is the primary action and Show more the open text button with ›, side by side in one row.
    expect(buttons[0]).toHaveClass("sk-btn--primary");
    expect(buttons[1]).toHaveClass("sk-btn--open");
    expect(buttons[1]?.querySelector("svg")).not.toBeNull();
    expect(buttons[0]?.parentElement).toBe(buttons[1]?.parentElement);
    // The 44 px minimum is the family stylesheet's, not an inline style. jsdom loads no CSS, so the rule is read here.
    expect(
      readStylesheet("features/mcp-apps/ui/family.css").rule(".sk-btn--open")[
        "min-height"
      ],
    ).toBe("var(--sk-tap)");
    for (const button of buttons) {
      expect(button).not.toHaveAttribute("style");
      expect(button).toHaveClass("work-compact-action");
    }

    await userEvent.click(screen.getByRole("button", { name: "Done" }));
    await userEvent.click(screen.getByRole("button", { name: "Show more" }));
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
    expect(screen.getByRole("button", { name: "Show task" })).toHaveClass(
      "sk-btn--open",
    );
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
    expect(screen.getByText("Kök · Hög")).toBeInTheDocument();
    const description = document.querySelector(".work-compact-description");
    expect(description?.textContent?.endsWith("…")).toBe(true);
    expect(description?.textContent?.length).toBeLessThanOrEqual(80);
    expect(description?.textContent).not.toContain("\n");
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
    expect(screen.queryByText("High")).toBeNull();
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
    expect(screen.getByText("Mål: 15 dec").closest("p")).toHaveTextContent(
      "Mål: 15 dec · 3 av 12 uppgifter klara · 2 försenade",
    );
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
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Det gick inte att läsa just nu",
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
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load this right now",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});
