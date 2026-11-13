import { agendaLabelsEn } from "@/features/work-app/agenda/agenda-labels";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import {
  shortTitle,
  UNDO_TITLE_MAX,
} from "@/features/work-app/agenda/agenda-undo";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn } from "@/features/work-app/shared/labels";
import {
  TASK_ID,
  task,
  makeTransport,
  renderAgenda,
  glyphOf,
  rowOf,
  undoButton,
  undoLineOf,
  openRow,
  resetAgendaEnvironment,
} from "./helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

it("a glyph tap marks the Task done at its version and offers Undo beside the status of the changed row", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  await waitFor(() =>
    expect(mock.updateTask).toHaveBeenCalledWith(
      TASK_ID,
      1,
      { status: "completed" },
      expect.any(String),
    ),
  );
  const line = await undoLineOf(task.title);
  expect(line).toHaveTextContent("Done");
  expect(line.parentElement).toHaveClass("work-agenda-undo");
  expect(
    within(line.parentElement as HTMLElement).getByRole("button", {
      name: `Undo ${task.title}`,
    }),
  ).toHaveTextContent(/^Undo$/);
});

it("a long Task title stays whole in its row, and its Undo line names only the status", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  const long =
    "Skicka den långa offerten till kunden i Göteborg med alla bilagorna";
  renderAgenda([{ ...task, title: long }], transport);
  await user.click(glyphOf(long));
  const line = await undoLineOf(long);
  expect(rowOf(long)).toHaveTextContent(long);
  expect(line).toHaveTextContent("Done");
  expect(line).not.toHaveTextContent(long);
});

it("shortTitle keeps a short title as it is, without its surrounding spaces", () => {
  expect(shortTitle("  Skicka offert ")).toBe("Skicka offert");
  expect(shortTitle("x".repeat(UNDO_TITLE_MAX))).toBe(
    "x".repeat(UNDO_TITLE_MAX),
  );
});

it("Undo writes the previous status against the new version with a new key", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  await user.click(await undoButton());
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
  expect(mock.updateTask).toHaveBeenLastCalledWith(
    TASK_ID,
    2,
    { status: "todo" },
    expect.any(String),
  );
  const [firstKey, secondKey] = mock.updateTask.mock.calls.map((call) =>
    String((call as unknown[])[3]),
  );
  expect(secondKey).not.toBe(firstKey);
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /^Undo/ }),
    ).not.toBeInTheDocument(),
  );
});

it("an Undo refused as a conflict shows the conflict notice and keeps the done status", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  const undo = await undoButton();
  mock.updateTask.mockRejectedValueOnce(
    Object.assign(new Error("conflict"), { code: "conflict" }),
  );
  await user.click(undo);
  expect(await screen.findByText(boardLabelsEn.conflict)).toBeInTheDocument();
  // The notice's button has a name of its own, so "Refresh" stays the toolbar's alone.
  expect(
    screen.getByRole("button", { name: boardLabelsEn.conflictAction }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: workEn.reload })).toHaveLength(
    1,
  );
  expect(mock.updateTask).toHaveBeenCalledTimes(2);
  expect(mock.updateTask).toHaveBeenLastCalledWith(
    TASK_ID,
    2,
    { status: "todo" },
    expect.any(String),
  );
});

it("an Undo whose reply does not show the restored status fails with Try again and a new key", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  const undo = await undoButton();
  // The server answers the Undo as if the change had not been reverted.
  mock.updateTask.mockResolvedValueOnce({
    task: {
      id: TASK_ID,
      title: "",
      status: "completed",
      due_at: null,
      version: 3,
    },
  });
  await user.click(undo);
  expect(await screen.findByRole("alert")).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: workEn.retry })).toHaveLength(1);
  expect(mock.getWorkAgenda).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(3));
  // The retry repeats the Undo at the version the first change returned, with a fresh key.
  const [, undoCall, retryCall] = mock.updateTask.mock.calls as unknown[][];
  expect(retryCall).toEqual([
    TASK_ID,
    2,
    { status: "todo" },
    expect.any(String),
  ]);
  expect(retryCall).not.toEqual(undoCall);
  expect((retryCall as unknown[])[3]).not.toBe((undoCall as unknown[])[3]);
});

it("the Undo line stays for fifteen seconds, then ends", async () => {
  vi.useFakeTimers();
  expect(UNDO_MS).toBe(15000);
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  fireEvent.click(glyphOf(task.title));
  // Lets the write settle under fake timers; waitFor would hang here because it polls with timers.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 1);
  });
  expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
});

it("the Undo time starts when the server has answered, not at the click, and the line says Moving until then", async () => {
  vi.useFakeTimers();
  const { transport, mock } = makeTransport();
  // The write stays open for five seconds after the click.
  let answer: () => void = () => undefined;
  mock.updateTask.mockImplementationOnce(
    (id: string, version: number, changes: { status: string }) =>
      new Promise((resolve) => {
        answer = () =>
          resolve({
            task: {
              id,
              title: "",
              status: changes.status,
              due_at: null,
              version: version + 1,
            },
          });
      }),
  );
  renderAgenda([task], transport);
  fireEvent.click(glyphOf(task.title));
  // The write starts in its row's queue, a microtask after the click.
  await act(async () => {
    await vi.advanceTimersByTimeAsync(5000);
  });
  expect(screen.getByText(agendaLabelsEn.moving)).toBeInTheDocument();
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
  await act(async () => {
    answer();
    await vi.advanceTimersByTimeAsync(0);
  });
  expect(screen.queryByText(agendaLabelsEn.moving)).not.toBeInTheDocument();
  expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
  // Fifteen seconds count from the answer, so the line is still there 14.9 s after it.
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 1);
  });
  expect(screen.getByRole("button", { name: /^Undo/ })).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
});

it("the pointer over the Undo line pauses its time, and it runs on with the time left when the pointer leaves", async () => {
  vi.useFakeTimers();
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  fireEvent.click(glyphOf(task.title));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  const undo = screen.getByRole("button", { name: /^Undo/ });
  // The pause sits on the Undo line's wrapper, which holds both the status text and the button.
  const line = undo.closest(".work-agenda-undo");
  if (!line) throw new Error("no Undo line");
  act(() => {
    vi.advanceTimersByTime(10000);
  });
  fireEvent.pointerEnter(line);
  act(() => {
    vi.advanceTimersByTime(UNDO_MS * 2);
  });
  // Far past the Undo time, the line is still there while the pointer is on it.
  expect(undo).toBeInTheDocument();
  fireEvent.pointerLeave(line);
  // Five seconds were left when the pointer came: they run down now.
  act(() => {
    vi.advanceTimersByTime(4999);
  });
  expect(undo).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
});

it("focus in the Undo line pauses its time as well, until focus leaves it", async () => {
  vi.useFakeTimers();
  const { transport } = makeTransport();
  renderAgenda([task], transport);
  fireEvent.click(glyphOf(task.title));
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
  const undo = screen.getByRole("button", { name: /^Undo/ });
  act(() => {
    undo.focus();
  });
  act(() => {
    vi.advanceTimersByTime(UNDO_MS * 2);
  });
  expect(undo).toBeInTheDocument();
  act(() => {
    undo.blur();
  });
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 1);
  });
  expect(undo).toBeInTheDocument();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
});

it("a refused change shows the board's conflict notice and keeps the status", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  mock.updateTask.mockRejectedValueOnce(
    Object.assign(new Error("conflict"), { code: "conflict" }),
  );
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  expect(await screen.findByText(boardLabelsEn.conflict)).toBeInTheDocument();
  // The notice's button has a name of its own, so "Refresh" stays the toolbar's alone.
  expect(
    screen.getByRole("button", { name: boardLabelsEn.conflictAction }),
  ).toBeInTheDocument();
  expect(screen.getAllByRole("button", { name: workEn.reload })).toHaveLength(
    1,
  );
  expect(
    screen.queryByRole("button", { name: /^Undo/ }),
  ).not.toBeInTheDocument();
  // Still not done, so the glyph action still says "mark done".
  expect(glyphOf(task.title)).toBeInTheDocument();
  expect(mock.getWorkAgenda).not.toHaveBeenCalled();
});

it("a failed change shows one Try again, and it sends the same write again with its key", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  mock.updateTask.mockRejectedValueOnce(new Error("network"));
  renderAgenda([task], transport);
  await user.click(glyphOf(task.title));
  const alert = await screen.findByRole("alert");
  // The notice text does not repeat the button's words: exactly one "Try again" in the notice.
  expect(alert.textContent?.split(workEn.retry)).toHaveLength(2);
  expect(screen.getAllByRole("button", { name: workEn.retry })).toHaveLength(1);
  await user.click(screen.getByRole("button", { name: workEn.retry }));
  await undoButton();
  expect(mock.updateTask).toHaveBeenCalledTimes(2);
  const [first, second] = mock.updateTask.mock.calls as unknown[][];
  expect(second).toEqual(first);
  expect(first).toEqual([
    TASK_ID,
    1,
    { status: "completed" },
    expect.any(String),
  ]);
});

it("the row's quick choices set any status, and the row's Undo line says the new one", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  openRow(task.title);
  const group = screen.getByRole("group", { name: workEn.status });
  await user.click(
    within(group).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  await waitFor(() =>
    expect(mock.updateTask).toHaveBeenCalledWith(
      TASK_ID,
      1,
      { status: "blocked" },
      expect.any(String),
    ),
  );
  const line = await undoLineOf(task.title);
  expect(line).toHaveTextContent("Blocked");
});

it("Undo after a status change from the quick choices writes the previous status at the new version", async () => {
  const user = userEvent.setup();
  const { transport, mock } = makeTransport();
  renderAgenda([task], transport);
  openRow(task.title);
  const group = screen.getByRole("group", { name: workEn.status });
  await user.click(
    within(group).getByRole("button", { name: workEn.taskStatus.blocked }),
  );
  await user.click(await undoButton());
  await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
  // The status the Task had before the change, written against the version the change returned (2).
  expect(mock.updateTask).toHaveBeenLastCalledWith(
    TASK_ID,
    2,
    { status: "todo" },
    expect.any(String),
  );
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /^Undo/ }),
    ).not.toBeInTheDocument(),
  );
});
