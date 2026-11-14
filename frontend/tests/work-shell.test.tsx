import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { TaskProps } from "@/features/work-app/tasks/task-detail-controls";
import { workEn } from "@/features/work-app/shared/labels";
import {
  WorkShell,
  type WorkShellProps,
} from "@/features/work-app/shell/work-shell";
import {
  workShellLabelsEn,
  workShellLabelsFor,
  workShellLabelsSv,
} from "@/features/work-app/shell/work-shell-labels";

function panels(): Pick<WorkShellProps, "agenda" | "board" | "hierarchy"> {
  return {
    agenda: <p>Innehåll agenda</p>,
    board: <p>Innehåll board</p>,
    hierarchy: <p>Innehåll hierarki</p>,
  };
}

describe.each([
  {
    name: "sv",
    labels: workShellLabelsSv,
    group: "Vyer",
    tabs: ["Agenda", "Status", "Projekt"],
  },
  {
    name: "en",
    labels: workShellLabelsEn,
    group: "Views",
    tabs: ["Agenda", "Status", "Projects"],
  },
])("WorkShell ($name)", ({ labels, group, tabs }) => {
  it("shows the tab strip in order, opens on Agenda, and shows only that tab's content", () => {
    render(<WorkShell labels={labels} {...panels()} />);

    const strip = screen.getByRole("group", { name: group });
    const buttons = within(strip).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual(tabs);
    expect(screen.getByRole("button", { name: tabs[0] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll agenda")).toBeInTheDocument();
    expect(screen.queryByText("Innehåll board")).not.toBeInTheDocument();
    expect(screen.queryByText("Innehåll hierarki")).not.toBeInTheDocument();
  });

  it("switches tab locally when a tab is pressed, without any callback", async () => {
    const user = userEvent.setup();
    render(<WorkShell labels={labels} {...panels()} />);

    await user.click(screen.getByRole("button", { name: tabs[1] }));

    expect(screen.getByRole("button", { name: tabs[1] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll board")).toBeVisible();
    // Agenda was pressed on open, so it stays mounted but hidden.
    expect(screen.getByText("Innehåll agenda")).not.toBeVisible();
    expect(screen.queryByText("Innehåll hierarki")).not.toBeInTheDocument();
  });

  it("keeps a visited tab mounted and hidden, and reports each pressed tab", async () => {
    const user = userEvent.setup();
    const onTabChange = vi.fn();
    render(
      <WorkShell labels={labels} {...panels()} onTabChange={onTabChange} />,
    );

    await user.click(screen.getByRole("button", { name: tabs[2] }));
    await user.click(screen.getByRole("button", { name: tabs[0] }));

    expect(onTabChange.mock.calls).toEqual([["hierarchy"], ["agenda"]]);
    expect(screen.getByText("Innehåll hierarki")).not.toBeVisible();
    expect(screen.getByText("Innehåll agenda")).toBeVisible();
  });

  it("opens on the tab given as initialTab", () => {
    render(<WorkShell labels={labels} initialTab="hierarchy" {...panels()} />);

    expect(screen.getByRole("button", { name: tabs[2] })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Innehåll hierarki")).toBeInTheDocument();
  });

  it("is a fullscreen frame with no detail region when no detail is given", () => {
    const { container } = render(<WorkShell labels={labels} {...panels()} />);

    expect(container.querySelector(".sk-frame")).toHaveAttribute(
      "data-mode",
      "full",
    );
    expect(container.querySelector(".sk-wide")).toBeInTheDocument();
    expect(
      screen.queryByRole("region", { name: labels.detailLabel }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: labels.back }),
    ).not.toBeInTheDocument();
  });

  it("shows the detail beside the list with a back button that calls onBack", async () => {
    const user = userEvent.setup();
    const onBack = vi.fn();
    const { container } = render(
      <WorkShell
        labels={labels}
        {...panels()}
        detail={<p>Detaljtext</p>}
        onBack={onBack}
      />,
    );

    expect(container.querySelector("[data-detail]")).toHaveAttribute(
      "data-detail",
      "open",
    );
    expect(screen.getByText("Innehåll agenda")).toBeInTheDocument();
    const detailRegion = screen.getByRole("region", {
      name: labels.detailLabel,
    });
    expect(within(detailRegion).getByText("Detaljtext")).toBeInTheDocument();

    await user.click(
      within(detailRegion).getByRole("button", { name: labels.back }),
    );
    expect(onBack).toHaveBeenCalledTimes(1);
  });

  it("does not show a back button when detail is given without onBack", () => {
    render(
      <WorkShell labels={labels} {...panels()} detail={<p>Detaljtext</p>} />,
    );

    expect(screen.getByText("Detaljtext")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: labels.back }),
    ).not.toBeInTheDocument();
  });
});

describe("task detail layout at 320 px", () => {
  it("has no status segments: the status and the due date are property chips", () => {
    render(
      <TaskProps
        hasDue={false}
        busy={false}
        status="todo"
        labels={workEn}
        onDue={vi.fn()}
        onStatus={vi.fn()}
        done={
          <button type="button" className="sk-btn sk-btn--compact">
            Done
          </button>
        }
      />,
    );

    expect(screen.queryByRole("radiogroup")).not.toBeInTheDocument();
    const done = screen.getByRole("button", { name: "Done" });
    for (const chip of screen.getAllByRole("button")) {
      if (chip !== done) expect(chip).toHaveClass("sk-chip", "work-prop-chip");
    }
    // Markera klar is the last control of the property row (task-detail-controls.tsx renders `done` after the chips).
    expect(done.parentElement?.lastElementChild).toBe(done);
  });
});

describe("workShellLabelsFor", () => {
  it("returns Swedish for sv locales and English for everything else", () => {
    expect(workShellLabelsFor("sv-SE")).toBe(workShellLabelsSv);
    expect(workShellLabelsFor("en-US")).toBe(workShellLabelsEn);
    expect(workShellLabelsFor("de")).toBe(workShellLabelsEn);
  });

  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(workShellLabelsSv.tabs).sort()).toEqual(
      Object.keys(workShellLabelsEn.tabs).sort(),
    );
    expect(Object.keys(workShellLabelsSv).sort()).toEqual(
      Object.keys(workShellLabelsEn).sort(),
    );
  });
});
