import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardLabelsEn, cardLabelsSv } from "@/features/work-app/card-labels";
import { WorkCard, type CardStatusWriter } from "@/features/work-app/work-card";
import type {
  WorkCardFrame,
  WorkItemRecord,
  WorkTask,
} from "@/features/work-app/transport";

const TASK_ID = "019f0000-0000-7000-8000-000000000001";

function item(overrides: Partial<WorkItemRecord> = {}): WorkItemRecord {
  return {
    kind: "task",
    id: TASK_ID,
    title: "Ring leverantören",
    status: "todo",
    due_at: null,
    version: 2,
    ...overrides,
  };
}

function frame(items: WorkItemRecord[]): WorkCardFrame {
  return { kind: "card", items, total: items.length, truncated: false };
}

function taskAt(version: number, status = "todo"): { task: WorkTask } {
  return {
    task: {
      id: TASK_ID,
      title: "Ring leverantören",
      status,
      due_at: null,
      version,
    },
  };
}

/** An error shaped like HostToolError: `code` is what writeFailure reads. */
function failure(code?: string): Error {
  return Object.assign(new Error("Tool request failed"), code ? { code } : {});
}

function writerMock(): {
  writer: CardStatusWriter;
  getTask: ReturnType<typeof vi.fn>;
  updateTask: ReturnType<typeof vi.fn>;
} {
  const getTask = vi.fn(() => Promise.resolve(taskAt(5)));
  const updateTask = vi.fn((_id: string, version: number) =>
    Promise.resolve(taskAt(version + 1, "completed")),
  );
  return {
    writer: {
      getTask,
      updateTask,
    } as unknown as CardStatusWriter,
    getTask,
    updateTask,
  };
}

function segmentButton(name: string) {
  const group = screen.getByRole("group", {
    name: cardLabelsEn.statusGroup,
  });
  return within(group).getByRole("button", { name });
}

describe("WorkCard status segments", () => {
  it("shows segments on Task rows only, when a writer is given", () => {
    const { writer } = writerMock();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([
          item({ status: "in_progress" }),
          item({
            id: "019f0000-0000-7000-8000-000000000002",
            kind: "project",
            status: "active",
          }),
        ])}
        writer={writer}
      />,
    );

    const groups = screen.getAllByRole("group", {
      name: cardLabelsEn.statusGroup,
    });
    expect(groups).toHaveLength(1);
    const pressed = within(groups[0]!).getByRole("button", {
      name: cardLabelsEn.taskStatus.in_progress,
    });
    expect(pressed).toHaveAttribute("aria-pressed", "true");
    expect(
      within(groups[0]!)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual([
      cardLabelsEn.taskStatus.todo,
      cardLabelsEn.taskStatus.in_progress,
      cardLabelsEn.taskStatus.blocked,
      cardLabelsEn.taskStatus.completed,
    ]);
    // Segments are 44 px touch targets through the shared action class (see work-card.test.tsx).
    expect(pressed).toHaveClass("work-compact-action");
  });

  it("renders no segments when no writer is given", () => {
    render(
      <WorkCard state="ready" labels={cardLabelsEn} frame={frame([item()])} />,
    );

    expect(screen.queryByRole("group")).toBeNull();
  });

  it("writes the shown version with update_task, updates the row and tells the host", async () => {
    const { writer, getTask, updateTask } = writerMock();
    const announce = vi.fn();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([item({ version: 2 })])}
        writer={writer}
        announce={announce}
      />,
    );

    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));

    expect(getTask).not.toHaveBeenCalled();
    expect(updateTask).toHaveBeenCalledTimes(1);
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      2,
      { status: "completed" },
      expect.any(String),
    );
    expect(segmentButton(cardLabelsEn.taskStatus.completed)).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(announce).toHaveBeenCalledWith(
      "Changed the status of 1 task to done.",
    );
  });

  it("sends the Swedish sentence for a Swedish card", async () => {
    const { writer } = writerMock();
    const announce = vi.fn();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame([item({ version: 2 })])}
        writer={writer}
        announce={announce}
      />,
    );

    await userEvent.click(
      within(
        screen.getByRole("group", { name: cardLabelsSv.statusGroup }),
      ).getByRole("button", { name: cardLabelsSv.taskStatus.completed }),
    );

    expect(announce).toHaveBeenCalledWith(
      "Ändrade status på 1 uppgift till klar.",
    );
  });

  it("reads the Task first when the row has no version", async () => {
    const { writer, getTask, updateTask } = writerMock();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([item({ version: undefined })])}
        writer={writer}
      />,
    );

    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));

    expect(getTask).toHaveBeenCalledWith(TASK_ID);
    expect(updateTask).toHaveBeenCalledWith(
      TASK_ID,
      5,
      { status: "completed" },
      expect.any(String),
    );
  });

  it("shows a conflict banner and Read again fetches the latest version", async () => {
    const { writer, getTask, updateTask } = writerMock();
    updateTask.mockRejectedValueOnce(failure("conflict"));
    getTask.mockResolvedValueOnce(taskAt(7, "in_progress"));
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([item({ version: 2 })])}
        writer={writer}
      />,
    );

    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));

    expect(screen.getByRole("alert")).toHaveTextContent(
      cardLabelsEn.statusConflict,
    );
    await userEvent.click(
      screen.getByRole("button", { name: cardLabelsEn.reread }),
    );

    expect(getTask).toHaveBeenCalledWith(TASK_ID);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(segmentButton(cardLabelsEn.taskStatus.in_progress)).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    // The next change uses the version just read, under a new key.
    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));
    expect(updateTask).toHaveBeenCalledTimes(2);
    expect(updateTask.mock.calls[1]?.[1]).toBe(7);
    expect(updateTask.mock.calls[1]?.[3]).not.toBe(
      updateTask.mock.calls[0]?.[3],
    );
  });

  it("retries a network failure with the same idempotency key and version", async () => {
    const { writer, updateTask } = writerMock();
    updateTask.mockRejectedValueOnce(failure());
    const announce = vi.fn();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([item({ version: 2 })])}
        writer={writer}
        announce={announce}
      />,
    );

    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));
    expect(screen.getByRole("alert")).toHaveTextContent(
      cardLabelsEn.statusFailed,
    );

    await userEvent.click(
      screen.getByRole("button", { name: cardLabelsEn.retry }),
    );

    expect(updateTask).toHaveBeenCalledTimes(2);
    const [first, second] = updateTask.mock.calls;
    expect(second?.[1]).toBe(first?.[1]);
    expect(second?.[3]).toBe(first?.[3]);
    expect(screen.queryByRole("alert")).toBeNull();
    expect(announce).toHaveBeenCalledTimes(1);
  });

  it("offers no retry for a refused write", async () => {
    const { writer, updateTask } = writerMock();
    updateTask.mockRejectedValueOnce(failure("forbidden"));
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame([item({ version: 2 })])}
        writer={writer}
      />,
    );

    await userEvent.click(segmentButton(cardLabelsEn.taskStatus.completed));

    expect(screen.getByRole("alert")).toHaveTextContent(
      cardLabelsEn.statusFailed,
    );
    expect(
      screen.queryByRole("button", { name: cardLabelsEn.retry }),
    ).toBeNull();
    expect(updateTask).toHaveBeenCalledTimes(1);
  });
});
