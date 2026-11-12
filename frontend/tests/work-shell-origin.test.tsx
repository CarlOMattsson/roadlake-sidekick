import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";

/*
 * The Work shell marks the other tabs out of date by the tab a write was made in, and keeps the mark until a read that
 * started after the write has given the tab its frame. Simulated: the transport is a mock, so this is not a test
 * against a real host.
 */

const agendaItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Agenda-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  agenda_group: "today",
};
const oldCard: WorkItemRecord = {
  ...agendaItem,
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Gammalt kort",
  agenda_group: undefined,
};
const newCard: WorkItemRecord = { ...oldCard, title: "Nytt kort" };
const agendaPage: WorkAgendaPage = { items: [agendaItem], next_cursor: null };
const agendaFrame: WorkFrame = {
  kind: "agenda",
  filters: {},
  page: agendaPage,
};
const pageWith = (card: WorkItemRecord): WorkBoardPage => ({
  columns: { todo: [card] },
  next_cursor: null,
});

type Deferred<T> = { promise: Promise<T>; resolve: (value: T) => void };
function deferred<T>(): Deferred<T> {
  let resolve: (value: T) => void = () => undefined;
  const promise = new Promise<T>((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

const done = {
  task: { ...agendaItem, status: "completed", version: 2 },
};

function shell(mocks: Record<string, ReturnType<typeof vi.fn>>) {
  const transport = {
    getWorkAgenda: vi.fn().mockResolvedValue(agendaPage),
    getWorkHierarchy: vi
      .fn()
      .mockResolvedValue({ kind: "hierarchy", nodes: [], truncated: false }),
    listUnsortedTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listDomains: vi.fn().mockResolvedValue([]),
    listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listSavedWorkViews: vi.fn().mockResolvedValue([]),
    ...mocks,
  } as unknown as WorkTransport;
  return render(
    <WorkFullscreen
      transport={transport}
      labels={workEn}
      shellLabels={workShellLabelsEn}
      initial={agendaFrame}
    />,
  );
}

const tab = (name: string) => screen.getByRole("button", { name });
const completeAgendaTask = () =>
  userEvent.click(
    screen.getByRole("button", { name: "Mark Agenda-uppgift as done" }),
  );
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("Work shell: invalidation by origin", () => {
  it("(7) an Agenda write that is answered after the Board was pressed still makes the Board read again", async () => {
    const write = deferred<typeof done>();
    const getWorkBoard = vi
      .fn()
      .mockResolvedValueOnce(pageWith(oldCard))
      .mockResolvedValue(pageWith(newCard));
    const updateTask = vi.fn(() => write.promise);
    shell({ getWorkBoard, updateTask });

    await userEvent.click(tab("Status"));
    expect(await screen.findByText("Gammalt kort")).toBeInTheDocument();
    await userEvent.click(tab("Agenda"));
    await completeAgendaTask();
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    // The Board is pressed while the Agenda's write is still on its way; the answer comes with the Board shown.
    await userEvent.click(tab("Status"));
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    await act(async () => {
      write.resolve(done);
      await Promise.resolve();
    });
    await settle();
    expect(getWorkBoard).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Nytt kort")).toBeInTheDocument();
  });

  it("(8) a mark made while the Board's first read is on its way is kept until a later read has answered", async () => {
    const first = deferred<WorkBoardPage>();
    const getWorkBoard = vi
      .fn()
      .mockReturnValueOnce(first.promise)
      .mockResolvedValue(pageWith(newCard));
    const updateTask = vi.fn().mockResolvedValue(done);
    shell({ getWorkBoard, updateTask });

    await userEvent.click(tab("Status"));
    expect(getWorkBoard).toHaveBeenCalledTimes(1);
    await userEvent.click(tab("Agenda"));
    await completeAgendaTask();
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    await settle();
    // The Board is pressed again before its first read answers; that read is from before the write.
    await userEvent.click(tab("Status"));
    await act(async () => {
      first.resolve(pageWith(oldCard));
      await Promise.resolve();
    });
    await settle();
    expect(getWorkBoard).toHaveBeenCalledTimes(2);
    expect(await screen.findByText("Nytt kort")).toBeInTheDocument();
  });
});
