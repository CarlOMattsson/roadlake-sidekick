import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RowMenuTip } from "@/features/work-app/shared/row-menu";
import { UNDO_MS } from "@/features/work-app/agenda/agenda-undo";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import type {
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const open: WorkStep = {
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Jämför priset med offerten från Bergström Bygg",
  status: "todo",
  due_at: null,
  version: 1,
  position: 0,
};
const done: WorkStep = { ...open, status: "completed", version: 2 };

function transportFor(steps: WorkStep[]): WorkTransport {
  return {
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: steps, next_cursor: null }),
    completeTaskStep: vi.fn().mockResolvedValue({ step: done }),
    updateTaskStep: vi
      .fn()
      .mockResolvedValue({ step: { ...open, version: 3 } }),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as WorkTransport;
}

beforeEach(() => {
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});
afterEach(() => vi.useRealTimers());

describe("a Step's Ångra", () => {
  it("stands in the checked Step's row with Klar as its meta line, and no notice box follows the list", async () => {
    const user = userEvent.setup();
    render(
      <TaskSteps
        taskId={TASK_ID}
        transport={transportFor([open])}
        labels={workSv}
      />,
    );
    await user.click(await screen.findByRole("checkbox", { name: open.title }));

    const undo = await screen.findByRole("button", { name: "Ångra" });
    const row = screen.getByRole("checkbox").closest("li");
    expect(undo.closest("li")).toBe(row);
    expect(undo).toHaveClass("sk-btn--secondary", "sk-btn--compact");
    expect(row).toHaveTextContent(/Klar/);
    // The title is not repeated in a notice under the list.
    expect(screen.queryByText(/Klar: /)).not.toBeInTheDocument();
    expect(document.querySelector(".work-manage-undo")).toBeNull();
  });

  it("says Open again in English after an uncheck, and runs out after the Undo time", async () => {
    vi.useFakeTimers({ shouldAdvanceTime: true });
    const user = userEvent.setup({ advanceTimers: vi.advanceTimersByTime });
    render(
      <TaskSteps
        taskId={TASK_ID}
        transport={transportFor([done])}
        labels={workEn}
      />,
    );
    await user.click(await screen.findByRole("checkbox", { name: open.title }));

    expect(await screen.findByRole("status")).toHaveTextContent("Open again");
    expect(screen.getByRole("button", { name: "Undo" })).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS + 100);
    });
    expect(screen.queryByRole("button", { name: "Undo" })).toBeNull();
  });
});

describe("the long-press tip", () => {
  it("shows only the last tip of a view and brings the earlier one back when the last leaves", () => {
    function Page({ last }: { last: boolean }) {
      return (
        <article>
          <section>
            <RowMenuTip labels={workSv} step />
          </section>
          <section>{last && <RowMenuTip labels={workSv} />}</section>
        </article>
      );
    }
    const { rerender } = render(<Page last />);
    const tips = () => [
      ...document.querySelectorAll<HTMLElement>(".work-row-tip"),
    ];
    expect(tips().map((tip) => tip.hidden)).toEqual([true, false]);

    rerender(<Page last={false} />);
    expect(tips().map((tip) => tip.hidden)).toEqual([false]);

    rerender(<Page last />);
    expect(tips().map((tip) => tip.hidden)).toEqual([true, false]);
  });

  it("draws nothing once a row menu has been used", () => {
    localStorage["sidekick.rowMenuUsed"] = "1";
    render(<RowMenuTip labels={workSv} />);
    expect(document.querySelector(".work-row-tip")).toBeNull();
  });
});
