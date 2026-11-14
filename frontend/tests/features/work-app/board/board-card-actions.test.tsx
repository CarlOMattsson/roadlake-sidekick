import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { BoardCard } from "@/features/work-app/board/board-card";
import { workEn, workStatusLabel } from "@/features/work-app/shared/labels";
import {
  TASK_STATUSES,
  type WorkItemRecord,
} from "@/features/work-app/transport/transport";

/*
 * The controls of one board card: the glyph in the two layouts, the quick choices (the group that opens
 * inside the card from a right click, a long press, Shift+F10 or the menu key), and the reorder buttons.
 * jsdom has no layout, so the 44 px touch targets are sized in work.css and are not measured here.
 */

const task: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Boka mötet med revisorn",
  status: "todo",
  due_at: null,
  version: 1,
};
const doneTask: WorkItemRecord = { ...task, status: "completed" };
const project: WorkItemRecord = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Renovering",
  status: "active",
  due_at: null,
  version: 1,
};

function dragHandlers() {
  return {
    onPointerDown: vi.fn(),
    onPointerMove: vi.fn(),
    onPointerUp: vi.fn(),
    onPointerCancel: vi.fn(),
    onKeyDown: vi.fn(),
  };
}

type Props = Parameters<typeof BoardCard>[0];

function renderCard(overrides: Partial<Props> = {}) {
  const base: Props = {
    item: task,
    labels: workEn,
    disabled: false,
    dragging: false,
    onOpen: vi.fn(),
    onMove: vi.fn(),
  };
  render(
    <ul>
      <BoardCard {...base} {...overrides} />
    </ul>,
  );
}

/** The title of a card: the button the keys open the group from and where focus returns. */
const titleOf = (title: string) => screen.getByText(title);
/** The card's own list item, found by its title. */
const rowOf = (title: string) => titleOf(title).closest("li") as HTMLElement;
const groupOf = (title: string) =>
  screen.getByRole("group", { name: boardLabelsEn.moveListFor(title) });

/** Opens the group the way a keyboard user does: focus on the title, then Shift+F10. */
async function openFromKeyboard(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  act(() => titleOf(title).focus());
  await user.keyboard("{Shift>}{F10}{/Shift}");
}

describe("columns layout", () => {
  it("keeps the drag handle with touch-action none and passes pointer events to the drag handlers", () => {
    const handlers = dragHandlers();
    renderCard({ drag: handlers });

    const handle = screen.getByRole("button", {
      name: boardLabelsEn.dragTaskFor(task.title),
    });
    expect(handle).toHaveClass("work-drag-handle");
    expect(handle.style.touchAction).toBe("none");
    expect(
      screen.queryByRole("button", {
        name: workEn.agendaComplete.replace("{title}", task.title),
      }),
    ).toBeNull();

    fireEvent.pointerDown(handle);
    expect(handlers.onPointerDown).toHaveBeenCalledTimes(1);
  });

  it("the drag handle takes a right click itself, so the quick choices do not open", () => {
    renderCard({ drag: dragHandlers() });

    const handle = screen.getByRole("button", {
      name: boardLabelsEn.dragTaskFor(task.title),
    });
    expect(fireEvent.contextMenu(handle)).toBe(false);
    expect(screen.queryByRole("group")).toBeNull();
  });
});

describe("single layout", () => {
  const glyphName = (title: string, status: WorkItemRecord["status"]) =>
    (status === "completed"
      ? workEn.agendaReopen
      : workEn.agendaComplete
    ).replace("{title}", title);

  it("has no drag handle: the glyph is a done toggle without drag props or touch-action", async () => {
    const user = userEvent.setup();
    const handlers = dragHandlers();
    const onToggleDone = vi.fn();
    renderCard({ layout: "single", drag: handlers, onToggleDone });

    expect(document.querySelector(".work-drag-handle")).toBeNull();
    const glyph = screen.getByRole("button", {
      name: glyphName(task.title, task.status),
    });
    expect(glyph).toHaveClass("work-card-done");
    expect(glyph.style.touchAction).toBe("");

    fireEvent.pointerDown(glyph);
    fireEvent.pointerMove(glyph);
    fireEvent.pointerUp(glyph);
    expect(handlers.onPointerDown).not.toHaveBeenCalled();
    expect(handlers.onPointerMove).not.toHaveBeenCalled();
    expect(handlers.onPointerUp).not.toHaveBeenCalled();

    await user.click(glyph);
    expect(onToggleDone).toHaveBeenCalledWith(task);
  });

  it("offers a completed Task as open again", async () => {
    const user = userEvent.setup();
    const onToggleDone = vi.fn();
    renderCard({ item: doneTask, layout: "single", onToggleDone });

    await user.click(
      screen.getByRole("button", {
        name: glyphName(doneTask.title, doneTask.status),
      }),
    );
    expect(onToggleDone).toHaveBeenCalledWith(doneTask);
  });

  it("the glyph does nothing without onToggleDone", () => {
    renderCard({ layout: "single" });
    expect(
      screen.getByRole("button", { name: glyphName(task.title, task.status) }),
    ).toBeDisabled();
  });

  it("Shift+F10 on the title opens the status group inside the card", async () => {
    const user = userEvent.setup();
    renderCard({ layout: "single" });

    await openFromKeyboard(user, task.title);
    expect(rowOf(task.title)).toContainElement(groupOf(task.title));
  });
});

describe("the quick choices of a card", () => {
  it("a Task card has no ⋯ button and no group until it is opened", () => {
    renderCard();
    expect(document.querySelector(".work-move-button")).toBeNull();
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("the title says the quick choices are behind Shift+F10 and a long press; a Project title says nothing of them", () => {
    render(
      <ul>
        <BoardCard
          item={task}
          labels={workEn}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
        />
        <BoardCard
          item={project}
          labels={workEn}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
        />
      </ul>,
    );
    const taskTitle = titleOf(task.title);
    expect(taskTitle).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
    expect(taskTitle).toHaveAttribute("aria-description", workEn.rowMenuHint);
    expect(titleOf(project.title)).not.toHaveAttribute("aria-keyshortcuts");
    expect(titleOf(project.title)).not.toHaveAttribute("aria-description");
  });

  it("a right click opens the group, and a second right click closes it and puts focus back on the title", () => {
    renderCard();

    fireEvent.contextMenu(rowOf(task.title));
    expect(groupOf(task.title)).toBeInTheDocument();

    fireEvent.contextMenu(rowOf(task.title));
    expect(screen.queryByRole("group")).toBeNull();
    expect(titleOf(task.title)).toHaveFocus();
  });

  it("Shift+F10 opens the group, and a second Shift+F10 closes it", async () => {
    const user = userEvent.setup();
    renderCard();

    await openFromKeyboard(user, task.title);
    expect(groupOf(task.title)).toBeInTheDocument();

    await user.keyboard("{Shift>}{F10}{/Shift}");
    expect(screen.queryByRole("group")).toBeNull();
    expect(titleOf(task.title)).toHaveFocus();
  });

  it("the menu key opens the group", () => {
    renderCard();

    fireEvent.keyDown(titleOf(task.title), { key: "ContextMenu" });
    expect(groupOf(task.title)).toBeInTheDocument();
  });

  it("the choices are in the Tab order after the title, and Escape closes the group and puts focus back on the title", async () => {
    const user = userEvent.setup();
    renderCard();

    await openFromKeyboard(user, task.title);
    await user.tab();
    expect(
      within(groupOf(task.title)).getByRole("button", {
        name: workStatusLabel(workEn, "todo"),
      }),
    ).toHaveFocus();
    await user.keyboard("{Escape}");

    expect(screen.queryByRole("group")).toBeNull();
    expect(titleOf(task.title)).toHaveFocus();
  });

  it("lists all four statuses, the current one pressed, and no Cancel", () => {
    renderCard();

    fireEvent.contextMenu(rowOf(task.title));
    const group = groupOf(task.title);
    for (const status of TASK_STATUSES) {
      expect(
        within(group).getByRole("button", {
          name: workStatusLabel(workEn, status),
        }),
      ).toHaveAttribute(
        "aria-pressed",
        status === task.status ? "true" : "false",
      );
    }
    expect(
      within(group).queryByRole("button", { name: workEn.cancel }),
    ).toBeNull();
  });

  it("picking another status calls onMove once and closes the group", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    renderCard({ onMove });

    await openFromKeyboard(user, task.title);
    const group = groupOf(task.title);
    await user.click(
      within(group).getByRole("button", {
        name: workStatusLabel(workEn, "in_progress"),
      }),
    );

    expect(onMove).toHaveBeenCalledTimes(1);
    expect(onMove).toHaveBeenCalledWith(task, "in_progress");
    expect(screen.queryByRole("group")).toBeNull();
  });

  it("picking the current status does nothing and keeps the group open", async () => {
    const user = userEvent.setup();
    const onMove = vi.fn();
    renderCard({ onMove });

    fireEvent.contextMenu(rowOf(task.title));
    const group = groupOf(task.title);
    await user.click(
      within(group).getByRole("button", {
        name: workStatusLabel(workEn, task.status),
      }),
    );

    expect(onMove).not.toHaveBeenCalled();
    expect(screen.getByRole("group")).toBe(group);
  });

  it("shows no reorder buttons without onReorder", async () => {
    const user = userEvent.setup();
    renderCard();

    await openFromKeyboard(user, task.title);
    expect(
      screen.queryByRole("button", { name: boardLabelsEn.moveUp }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: boardLabelsEn.moveDown }),
    ).toBeNull();
  });

  it("with onReorder, Flytta upp calls onReorder(card, -1) and is disabled at the top", async () => {
    const user = userEvent.setup();
    const onReorder = vi.fn();
    renderCard({ onReorder, canMoveUp: false, canMoveDown: true });

    fireEvent.contextMenu(rowOf(task.title));
    const up = screen.getByRole("button", { name: boardLabelsEn.moveUp });
    const down = screen.getByRole("button", { name: boardLabelsEn.moveDown });
    expect(up).toBeDisabled();
    expect(down).toBeEnabled();

    await user.click(down);
    expect(onReorder).toHaveBeenCalledWith(task, 1);
  });

  it("with onReorder, Flytta ned is disabled at the bottom and Flytta upp calls with -1", async () => {
    const user = userEvent.setup();
    const onReorder = vi.fn();
    renderCard({ onReorder, canMoveUp: true, canMoveDown: false });

    await openFromKeyboard(user, task.title);
    expect(
      screen.getByRole("button", { name: boardLabelsEn.moveDown }),
    ).toBeDisabled();

    await user.click(
      screen.getByRole("button", { name: boardLabelsEn.moveUp }),
    );
    expect(onReorder).toHaveBeenCalledWith(task, -1);
  });

  it("a Project card has no group, no quick choices and no drag handle", () => {
    renderCard({ item: project });
    fireEvent.contextMenu(rowOf(project.title));
    expect(screen.queryByRole("group")).toBeNull();
    expect(document.querySelector(".work-move-button")).toBeNull();
    expect(document.querySelector(".work-drag-handle")).toBeNull();
    expect(document.querySelector(".work-card-done")).toBeNull();
  });
});

describe("one group at a time", () => {
  it("opening the group of one card closes the group that was open on another card", () => {
    const other: WorkItemRecord = {
      ...task,
      id: "019f0000-0000-7000-8000-0000000000b2",
      title: "Ring Anna om offerten",
    };
    render(
      <ul>
        <BoardCard
          item={task}
          labels={workEn}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
        />
        <BoardCard
          item={other}
          labels={workEn}
          disabled={false}
          dragging={false}
          onOpen={vi.fn()}
          onMove={vi.fn()}
        />
      </ul>,
    );

    fireEvent.contextMenu(rowOf(task.title));
    expect(groupOf(task.title)).toBeInTheDocument();

    fireEvent.contextMenu(rowOf(other.title));
    expect(groupOf(other.title)).toBeInTheDocument();
    expect(
      screen.queryByRole("group", {
        name: boardLabelsEn.moveListFor(task.title),
      }),
    ).toBeNull();
    expect(screen.getAllByRole("group")).toHaveLength(1);
  });
});
