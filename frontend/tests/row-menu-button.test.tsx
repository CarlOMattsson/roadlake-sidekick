import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { BoardCard } from "@/features/work-app/board/board-card";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * The row menu has a button for a screen reader on every Task row of Agenda and Status and on every
 * Step of the Task view. It is drawn nowhere (work-visually-hidden), opens the same menu as the long press, puts the
 * focus on the menu's first choice, and Escape gives the focus back to it. jsdom has no layout: the 1 px clip is CSS.
 */

if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

afterEach(() => {
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

const task: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Skicka offert",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};
const project: WorkItemRecord = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Kök",
  status: "active",
  due_at: null,
  version: 1,
  agenda_group: "today",
};

describe("Agenda row", () => {
  function renderAgenda(labels: typeof workEn = workSv) {
    const frame: WorkAgendaFrame = {
      kind: "agenda",
      filters: {},
      page: { items: [task, project], next_cursor: null },
    };
    render(
      <AgendaView
        frame={frame}
        onChange={vi.fn()}
        transport={{} as unknown as WorkTransport}
        labels={labels}
        moves={0}
        onOpen={vi.fn()}
        shortcuts={false}
      />,
    );
  }

  it("opens the menu with focus on the first choice; Escape closes it and focus is back on the button", async () => {
    const user = userEvent.setup();
    renderAgenda();
    const button = screen.getByRole("button", {
      name: "Fler val för Skicka offert",
    });
    expect(button).toHaveClass("work-visually-hidden");
    // A sibling of the row's controls, not inside another button; a Project has none.
    expect(button.parentElement?.tagName).toBe("LI");
    expect(
      screen.queryByRole("button", { name: "Fler val för Kök" }),
    ).not.toBeInTheDocument();

    await user.click(button);
    const menu = within(button.closest("li") as HTMLElement).getByRole(
      "group",
      { name: workSv.status },
    );
    expect(menu).toBeInTheDocument();
    const first = within(menu).getAllByRole("button")[0];
    expect(first).toHaveFocus();
    expect(first).toHaveClass("sk-chip");

    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("group", { name: workSv.status }),
    ).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("the close button also returns to the button; the long press still returns to the title", async () => {
    const user = userEvent.setup();
    renderAgenda();
    const button = screen.getByRole("button", {
      name: "Fler val för Skicka offert",
    });
    await user.click(button);
    await user.click(screen.getByRole("button", { name: workSv.closeMenu }));
    expect(button).toHaveFocus();

    // Opened by a long press afterwards: Escape goes to the title as before.
    const row = button.closest("li") as HTMLElement;
    fireEvent.contextMenu(row);
    expect(
      screen.getByRole("group", { name: workSv.status }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(screen.getByRole("button", { name: "Skicka offert" })).toHaveFocus();
  });

  it("has the English name", () => {
    renderAgenda(workEn);
    expect(
      screen.getByRole("button", { name: "More options for Skicka offert" }),
    ).toBeInTheDocument();
  });
});

describe("Status card", () => {
  it("opens the status group with focus on the first status; Escape returns to the button", async () => {
    const user = userEvent.setup();
    render(
      <ul>
        <BoardCard
          item={task}
          labels={workSv}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
          layout="single"
        />
      </ul>,
    );
    const button = screen.getByRole("button", {
      name: "Fler val för Skicka offert",
    });
    expect(button.parentElement?.tagName).toBe("LI");
    await user.click(button);
    const group = screen.getByRole("group", {
      name: workSv.moveListFor(task.title),
    });
    expect(within(group).getAllByRole("button")[0]).toHaveFocus();
    expect(document.documentElement.dataset.rowMenu).toBe("1");

    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("group", { name: workSv.moveListFor(task.title) }),
    ).not.toBeInTheDocument();
    expect(button).toHaveFocus();
  });

  it("a Project card has no such button", () => {
    render(
      <ul>
        <BoardCard
          item={project}
          labels={workSv}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
        />
      </ul>,
    );
    expect(
      screen.queryByRole("button", { name: /Fler val för/ }),
    ).not.toBeInTheDocument();
  });
});

describe("Step in the Task view", () => {
  const step = (id: string, title: string, version: number): WorkStep => ({
    id,
    title,
    status: "todo",
    due_at: null,
    version,
    position: 0,
  });
  const stepA = step("019f0000-0000-7000-8000-0000000000c1", "Ring Anna", 1);
  const stepB = step("019f0000-0000-7000-8000-0000000000c2", "Skriv offert", 2);

  it("opens the Step's menu with focus on its first enabled button; Escape returns to the button", async () => {
    const user = userEvent.setup();
    const transport = {
      listTaskSteps: vi
        .fn()
        .mockResolvedValue({ items: [stepA, stepB], next_cursor: null }),
      listStepActions: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    } as unknown as WorkTransport;
    render(
      <TaskSteps
        taskId="019f0000-0000-7000-8000-0000000000a1"
        transport={transport}
        labels={workSv}
      />,
    );
    const button = await screen.findByRole("button", {
      name: "Fler val för Ring Anna",
    });
    expect(button.parentElement?.tagName).toBe("LI");
    await user.click(button);
    const row = button.closest("li") as HTMLElement;
    const menu = row.querySelector(".work-step-menu") as HTMLElement;
    expect(menu).toBeInTheDocument();
    // The first Step cannot move up: the first enabled button is "Ned".
    expect(
      within(menu)
        .getAllByRole("button")
        .find((b) => !(b as HTMLButtonElement).disabled),
    ).toHaveFocus();

    await user.keyboard("{Escape}");
    expect(row.querySelector(".work-step-menu")).toBeNull();
    expect(button).toHaveFocus();
  });
});
