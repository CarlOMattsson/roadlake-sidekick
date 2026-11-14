import { act, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { hierarchyDetailLabelsSv } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { taskStatusLabel, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import { deferred } from "@tests/helpers/deferred";

/*
 * A read that started before a successful write must not put the older data back when it answers
 * late. The read ticket of the detail frame moves on with the write, so that answer is dropped.
 */

// The board is a stand-in that can send two patches in one event, as two rows answering together do.
vi.mock("@/features/work-app/board/board", async (importOriginal) => {
  const original =
    await importOriginal<typeof import("@/features/work-app/board/board")>();
  return {
    ...original,
    BoardView: ({
      frame,
      onChange,
    }: {
      frame: WorkBoardFrame;
      onChange: (next: WorkBoardFrame) => void;
    }) => (
      <div>
        <p data-testid="column">{frame.column ?? "none"}</p>
        <button
          type="button"
          onClick={() => {
            onChange({ ...frame, column: "first" });
            onChange({ ...frame, column: "second" });
          }}
        >
          patch twice
        </button>
      </div>
    ),
  };
});

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";

const emptyPage = { items: [], next_cursor: null };

function taskTransport(overrides: Record<string, unknown>): WorkTransport {
  return {
    listTaskContacts: vi.fn().mockResolvedValue(emptyPage),
    listTaskSteps: vi.fn().mockResolvedValue(emptyPage),
    listStepActions: vi.fn().mockResolvedValue(emptyPage),
    listTaskExternalReferences: vi.fn().mockResolvedValue(emptyPage),
    ...overrides,
  } as unknown as WorkTransport;
}

describe("Task detail: a late read does not undo a successful write", () => {
  it("keeps the saved status when an older read answers after the write", async () => {
    const user = userEvent.setup();
    const before: WorkTask = {
      id: TASK_ID,
      title: "Ring leverantören",
      status: "todo",
      due_at: null,
      version: 1,
    };
    const saved: WorkTask = { ...before, status: "blocked", version: 2 };
    const late = deferred<{ task: WorkTask }>();
    const getTask = vi
      .fn()
      .mockResolvedValueOnce({ task: before })
      .mockReturnValueOnce(late.promise);
    const updateTask = vi.fn().mockResolvedValue({ task: saved });
    const transport = taskTransport({ getTask, updateTask });
    const initial = { kind: "task" as const, id: TASK_ID };
    const view = (refreshKey: number) => (
      <WorkView
        transport={transport}
        initial={initial}
        labels={workSv}
        refreshKey={refreshKey}
      />
    );
    const { rerender } = render(view(0));
    const chip = (status: "todo" | "blocked") =>
      screen.findByRole("button", {
        name: `${hierarchyDetailLabelsSv.changeStatus}: ${taskStatusLabel(workSv, status)}`,
      });
    await chip("todo");

    // Read A: a refresh asks again and hangs.
    rerender(view(1));
    expect(getTask).toHaveBeenCalledTimes(2);

    // Write B: Blockerad is chosen and saved.
    await user.click(await chip("todo"));
    await user.click(
      within(screen.getByRole("group", { name: workSv.status })).getByRole(
        "button",
        { name: taskStatusLabel(workSv, "blocked") },
      ),
    );
    await chip("blocked");
    expect(updateTask).toHaveBeenCalledTimes(1);

    // A answers late with the older Task: the screen still shows B.
    await act(async () => {
      late.resolve({ task: before });
      await late.promise;
    });
    await chip("blocked");
    expect(
      screen.queryByRole("button", {
        name: `${hierarchyDetailLabelsSv.changeStatus}: ${taskStatusLabel(workSv, "todo")}`,
      }),
    ).not.toBeInTheDocument();
  });
});

describe("replaceFrame: two patches in one batch", () => {
  it("keeps the last patch when the first already replaced the frame", async () => {
    const user = userEvent.setup();
    const initial: WorkBoardFrame = {
      kind: "board",
      filters: {} as WorkBoardFrame["filters"],
      page: { columns: [] } as unknown as WorkBoardFrame["page"],
    };
    render(
      <WorkView
        transport={{} as unknown as WorkTransport}
        initial={initial}
        labels={workSv}
      />,
    );
    expect(screen.getByTestId("column")).toHaveTextContent("none");
    await user.click(screen.getByRole("button", { name: "patch twice" }));
    expect(screen.getByTestId("column")).toHaveTextContent("second");
  });
});
