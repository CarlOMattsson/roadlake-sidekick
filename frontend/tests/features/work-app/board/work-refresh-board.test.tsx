import { act, fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { expect, it, vi } from "vitest";

import { BoardView } from "@/features/work-app/board/board";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { elementWithText } from "@tests/helpers/exact-text";
import { deferred } from "@tests/helpers/deferred";
import { columnTab, tabNames } from "./column-tabs";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";

const todoCard: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const doingCard: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c2",
  title: "Boka målare",
  status: "in_progress",
  due_at: null,
  version: 2,
};
const newDoingCard: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c3",
  title: "Skicka faktura",
  status: "in_progress",
  due_at: null,
  version: 1,
};

const before: WorkBoardPage = {
  columns: {
    todo: [todoCard],
    in_progress: [doingCard],
    completed: [],
    active: [],
    paused: [],
  },
  next_cursor: null,
};

/** The board's frame lives in a parent, as in the work view, so a read that lands replaces the page. */
function Harness({
  transport,
  refreshKey,
}: {
  transport: WorkTransport;
  refreshKey: number;
}) {
  const [frame, setFrame] = useState<WorkBoardFrame>({
    kind: "board",
    filters: {},
    page: before,
  });
  return (
    <BoardView
      frame={frame}
      onChange={setFrame}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      layout="single"
      refreshKey={refreshKey}
    />
  );
}

it("reads again in place when refreshKey changes: every column tab stays, old cards stay until the answer lands", async () => {
  const answer = deferred<WorkBoardPage>();
  const getWorkBoard = vi.fn().mockReturnValue(answer.promise);
  const transport = { getWorkBoard } as unknown as WorkTransport;
  const { rerender } = render(<Harness transport={transport} refreshKey={0} />);

  fireEvent.click(columnTab(workEn.taskStatus.in_progress));
  expect(
    elementWithText(`${workEn.taskStatus.in_progress} (1)`, "h3"),
  ).toBeInTheDocument();
  expect(screen.getByText(doingCard.title)).toBeInTheDocument();

  rerender(<Harness transport={transport} refreshKey={1} />);

  expect(getWorkBoard).toHaveBeenCalledTimes(1);
  expect(getWorkBoard).toHaveBeenCalledWith({});
  expect(screen.getByText(doingCard.title)).toBeInTheDocument();

  act(() => {
    answer.resolve({
      ...before,
      columns: { ...before.columns, in_progress: [doingCard, newDoingCard] },
    });
  });

  expect(await screen.findByText(newDoingCard.title)).toBeInTheDocument();
  expect(
    elementWithText(`${workEn.taskStatus.in_progress} (2)`, "h3"),
  ).toBeInTheDocument();
  expect(tabNames(boardLabelsEn.columnTabs)).toContain(
    `${workEn.taskStatus.in_progress} 2`,
  );
  // No status is picked by the read: the To do tab stays, with its card one press away.
  fireEvent.click(columnTab(workEn.taskStatus.todo));
  expect(screen.getByText(todoCard.title)).toBeInTheDocument();
});

it("a read again that fails is an error MessageBox over the list that stays", async () => {
  const getWorkBoard = vi
    .fn()
    .mockRejectedValueOnce(new TypeError("Failed to fetch"))
    .mockResolvedValueOnce(before);
  const transport = { getWorkBoard } as unknown as WorkTransport;
  const { rerender, container } = render(
    <Harness transport={transport} refreshKey={0} />,
  );
  fireEvent.click(columnTab(workEn.taskStatus.in_progress));
  rerender(<Harness transport={transport} refreshKey={1} />);

  const alert = await screen.findByRole("alert");
  expect(alert).toHaveClass("sk-message", "sk-message--error");
  expect(alert).toHaveTextContent("Couldn’t refresh");
  // The list stays under the row, and the board's own notice (a bare paragraph with a button) is gone.
  expect(screen.getByText(doingCard.title)).toBeInTheDocument();
  expect(container.querySelector("p[role='alert'] > button")).toBeNull();
  const retry = screen.getByRole("button", { name: "Try again" });
  expect(retry).toHaveClass("sk-btn--secondary", "sk-btn--compact");
  expect(retry).not.toHaveClass("sk-btn--tonal");
  await act(() => {
    retry.click();
    return Promise.resolve();
  });
  expect(getWorkBoard).toHaveBeenCalledTimes(2);
  expect(screen.queryByRole("alert")).not.toBeInTheDocument();
});
