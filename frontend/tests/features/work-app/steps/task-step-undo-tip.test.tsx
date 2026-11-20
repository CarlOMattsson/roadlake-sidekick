import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { RowMenuTip } from "@/features/work-app/shared/row-menu";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { rowReceipt } from "@/features/work-app/shared/use-undo-receipts";
import { receiptRunning } from "@tests/helpers/receipt-bar";
import { TaskSteps } from "@tests/helpers/steps-with-bar";
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
  it("keeps Klar as the checked Step's meta line, with Ångra only in the receipt bar", async () => {
    const user = userEvent.setup();
    render(
      <TaskSteps
        taskId={TASK_ID}
        transport={transportFor([open])}
        labels={workSv}
      />,
    );
    await user.click(await screen.findByRole("checkbox", { name: open.title }));

    const undo = await screen.findByRole("button", { name: /^Ångra/ });
    const row = screen.getByRole("checkbox").closest("li");
    // The row says its new state and has no button of its own; the bar confirms it and holds Ångra.
    expect(undo.closest("li")).toBeNull();
    expect(undo.closest(".sk-receipt-slot")).toHaveTextContent(
      rowReceipt("Klar", open.title),
    );
    expect(row).toHaveTextContent(/Klar/);
    expect(row?.querySelector(".sk-undo-time")).toBeNull();
    expect(document.querySelector(".work-manage-undo")).toBeNull();
  });

  it("says Reopened in English after an uncheck, and the receipt runs out after the Undo time", async () => {
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

    const slot = document.querySelector(".sk-receipt-slot") as HTMLElement;
    await waitFor(() =>
      expect(slot).toHaveTextContent(rowReceipt("Reopened", open.title)),
    );
    const row = screen.getByRole("checkbox").closest("li");
    expect(row).toHaveTextContent("Reopened");
    expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
    await receiptRunning();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS + 100);
    });
    expect(screen.queryByRole("button", { name: /^Undo/ })).toBeNull();
    // The row's line ends with the bar's time.
    expect(row).not.toHaveTextContent("Reopened");
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
