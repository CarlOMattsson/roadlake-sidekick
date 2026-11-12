import { act, fireEvent, render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";

const NOW = new Date(2026, 9, 29, 10, 0);
const first: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Betala fakturan",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};
const second: WorkItemRecord = {
  ...first,
  id: "019f0000-0000-7000-8000-0000000000d2",
  title: "Boka målare",
};

type Call = { id: string; version: number; changes: WorkTaskChanges };

/** Every updateTask hangs until the test answers it; `answer(n)` answers the nth call as the server would. */
function makeTransport() {
  const calls: Call[] = [];
  const answers: Array<() => void> = [];
  const updateTask = vi.fn(
    (id: string, version: number, changes: WorkTaskChanges) =>
      new Promise((resolve) => {
        calls.push({ id, version, changes });
        answers.push(() =>
          resolve({
            task: {
              id,
              title: "",
              status: changes.status ?? "todo",
              due_at: null,
              version: version + 1,
            },
          }),
        );
      }),
  );
  const getWorkAgenda = vi.fn();
  const getTask = vi.fn();
  const transport = {
    updateTask,
    getTask,
    getWorkAgenda,
  } as unknown as WorkTransport;
  return { transport, updateTask, getWorkAgenda, getTask, calls, answers };
}

function renderAgenda(items: WorkItemRecord[], transport: WorkTransport) {
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items, next_cursor: null },
  };
  return render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      now={NOW}
    />,
  );
}

function glyph(title: string): HTMLElement {
  return screen.getByRole("button", {
    name: fillLabel(workEn.agendaComplete, { title }),
  });
}

/** Lets the queue start its task and a settled promise run its continuation. */
async function settle() {
  await act(async () => {
    await Promise.resolve();
    await Promise.resolve();
    await Promise.resolve();
  });
}

it("a second tap on a row whose write is running waits, shows 'Waiting…' at once and writes against the version the first write left", async () => {
  const { transport, calls, answers, getWorkAgenda, getTask } = makeTransport();
  renderAgenda([first], transport);
  fireEvent.click(glyph(first.title));
  await settle();
  expect(calls).toHaveLength(1);
  expect(calls[0]).toMatchObject({
    version: 1,
    changes: { status: "completed" },
  });
  // The second tap is not dropped and not disabled: it waits, and the row says so.
  expect(glyph(first.title)).toBeEnabled();
  fireEvent.click(glyph(first.title));
  expect(screen.getByText(workEn.queued)).toHaveClass("sk-queued");
  expect(screen.getByRole("listitem")).toHaveAttribute("aria-busy", "true");
  await settle();
  expect(calls).toHaveLength(1);
  act(() => {
    answers[0]!();
  });
  await settle();
  // Two taps are done, then open again: the second write is against version 2 and re-opens the Task.
  expect(calls).toHaveLength(2);
  expect(calls[1]).toMatchObject({ version: 2, changes: { status: "todo" } });
  act(() => {
    answers[1]!();
  });
  await settle();
  expect(screen.queryByText(workEn.queued)).not.toBeInTheDocument();
  expect(screen.getByRole("listitem")).not.toHaveAttribute("aria-busy");
  expect(getWorkAgenda).not.toHaveBeenCalled();
  expect(getTask).not.toHaveBeenCalled();
});

it("a tap on another row runs at once while the first row's write hangs", async () => {
  const { transport, calls } = makeTransport();
  renderAgenda([first, second], transport);
  fireEvent.click(glyph(first.title));
  await settle();
  fireEvent.click(glyph(second.title));
  await settle();
  expect(calls.map((call) => call.id)).toEqual([first.id, second.id]);
  expect(screen.queryByText(workEn.queued)).not.toBeInTheDocument();
});

it("one 'done' tap is one update_task and no read of the agenda", async () => {
  const { transport, updateTask, getWorkAgenda, getTask, answers } =
    makeTransport();
  renderAgenda([first], transport);
  fireEvent.click(glyph(first.title));
  await settle();
  act(() => {
    answers[0]!();
  });
  await settle();
  expect(updateTask).toHaveBeenCalledTimes(1);
  expect(getWorkAgenda).not.toHaveBeenCalled();
  expect(getTask).not.toHaveBeenCalled();
  expect(
    screen.getByRole("button", { name: workEn.agendaUndo }),
  ).toBeInTheDocument();
});

it("a read asked for while a row write runs waits for it instead of being dropped", async () => {
  const { transport, answers, getWorkAgenda } = makeTransport();
  getWorkAgenda.mockResolvedValue({ items: [], next_cursor: null });
  renderAgenda([first], transport);
  fireEvent.click(glyph(first.title));
  await settle();
  fireEvent.click(screen.getByRole("button", { name: workEn.refresh }));
  await settle();
  expect(getWorkAgenda).not.toHaveBeenCalled();
  act(() => {
    answers[0]!();
  });
  await settle();
  expect(getWorkAgenda).toHaveBeenCalledTimes(1);
});

it("(10) the waiting mark is announced from a status region that is mounted before it and is not inside the busy row", async () => {
  const { transport } = makeTransport();
  renderAgenda([first], transport);
  const region = screen.getByRole("status");
  expect(region).toBeEmptyDOMElement();

  fireEvent.click(glyph(first.title));
  await settle();
  fireEvent.click(glyph(first.title));
  expect(screen.getByRole("listitem")).toHaveAttribute("aria-busy", "true");
  // The same region, not a new one inside the busy row, now carries the news.
  expect(screen.getByRole("status")).toBe(region);
  expect(region).toHaveTextContent(`${first.title}: ${workEn.queued}`);
  expect(region.closest("[aria-busy]")).toBeNull();
});

it("(N2) a tap queued behind a write that got no answer replays that write first, then writes its own intent with its own key", async () => {
  let fail: (error: Error) => void = () => undefined;
  const updateTask = vi
    .fn()
    .mockReturnValueOnce(
      new Promise((_, reject) => {
        fail = reject;
      }),
    )
    .mockResolvedValueOnce({
      task: { ...first, status: "completed", version: 2 },
    })
    .mockResolvedValue({ task: { ...first, status: "todo", version: 3 } });
  renderAgenda([first], { updateTask } as unknown as WorkTransport);
  fireEvent.click(glyph(first.title));
  await settle();
  fireEvent.click(glyph(first.title));
  await act(async () => {
    fail(new Error("timeout"));
    await Promise.resolve();
  });
  await settle();
  await settle();
  expect(updateTask).toHaveBeenCalledTimes(3);
  const [one, replay, own] = updateTask.mock.calls;
  // The unsure write is replayed with its key; the second tap is a new write from the state the replay showed.
  expect(replay?.slice(0, 3)).toEqual(one?.slice(0, 3));
  expect(replay?.[3]).toBe(one?.[3]);
  expect(own?.[1]).toBe(2);
  expect(own?.[2]).toEqual({ status: "todo" });
  expect(own?.[3]).not.toBe(one?.[3]);
});

it("(N2b) a tap queued behind an Undo that got no answer replays the Undo first, then writes its own intent against the version it left", async () => {
  let fail: (error: Error) => void = () => undefined;
  const updateTask = vi
    .fn()
    // The change itself: todo -> completed.
    .mockResolvedValueOnce({
      task: { ...first, status: "completed", version: 2 },
    })
    // The Undo: its reply is lost.
    .mockReturnValueOnce(
      new Promise((_, reject) => {
        fail = reject;
      }),
    )
    // The Undo's replay: the server had applied it (completed -> todo, version 3).
    .mockResolvedValueOnce({ task: { ...first, status: "todo", version: 3 } })
    // The tap that came after: judged against version 3, not the stale 2.
    .mockResolvedValue({ task: { ...first, status: "completed", version: 4 } });
  renderAgenda([first], { updateTask } as unknown as WorkTransport);
  fireEvent.click(glyph(first.title));
  await settle();
  fireEvent.click(screen.getByRole("button", { name: workEn.agendaUndo }));
  await settle();
  // The row still shows "done" while the Undo has no answer; the tap is decided when it runs, after the replay.
  fireEvent.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaReopen, { title: first.title }),
    }),
  );
  await act(async () => {
    fail(new Error("timeout"));
    await Promise.resolve();
  });
  await settle();
  await settle();
  expect(updateTask).toHaveBeenCalledTimes(4);
  const [, undo, replay, own] = updateTask.mock.calls;
  expect(undo?.[1]).toBe(2);
  expect(undo?.[2]).toEqual({ status: "todo" });
  // The unsure Undo is replayed with its own key, once; the later tap is a new write from the version it left.
  expect(replay?.slice(0, 3)).toEqual(undo?.slice(0, 3));
  expect(replay?.[3]).toBe(undo?.[3]);
  expect(own?.[1]).toBe(3);
  expect(own?.[2]).toEqual({ status: "completed" });
  expect(own?.[3]).not.toBe(undo?.[3]);
  expect(screen.queryByRole("alert")).toBeNull();
});

it("(N4) a read asked for while another read runs is made when that one ends", async () => {
  let answer: (page: {
    items: WorkItemRecord[];
    next_cursor: null;
  }) => void = () => undefined;
  const getWorkAgenda = vi
    .fn()
    .mockReturnValueOnce(
      new Promise((resolve) => {
        answer = resolve;
      }),
    )
    .mockResolvedValue({ items: [second], next_cursor: null });
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items: [first], next_cursor: null },
  };
  const view = (refreshKey: number) => (
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={{ getWorkAgenda } as unknown as WorkTransport}
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      now={NOW}
      refreshKey={refreshKey}
    />
  );
  const { rerender } = render(view(0));
  rerender(view(1));
  await settle();
  expect(getWorkAgenda).toHaveBeenCalledTimes(1);
  rerender(view(2));
  await settle();
  expect(getWorkAgenda).toHaveBeenCalledTimes(1);
  await act(async () => {
    answer({ items: [first], next_cursor: null });
    await Promise.resolve();
  });
  await settle();
  await settle();
  expect(getWorkAgenda).toHaveBeenCalledTimes(2);
});
