import { act, render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn } from "@/features/work-app/labels";
import { savedViewsLabelsEn } from "@/features/work-app/saved-views-labels";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkFrame,
  WorkHierarchyFrame,
  WorkItemRecord,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport";
import { WorkFullscreen } from "@/features/work-app/work-fullscreen";
import { workShellLabelsEn } from "@/features/work-app/work-shell-labels";

// Performance: the Work shell reads only what is shown. A hidden room reads nothing, the To sort count is read once
// per refreshKey, a write in the shell makes the other tabs out of date (read when pressed), a Task made twice is
// listed once, and the saved views list is read once for the Agenda's and the Board's bar together.
// Every number below is a count of calls on the transport mock.

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
const boardItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Board-uppgift",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
};
const agendaPage: WorkAgendaPage = { items: [agendaItem], next_cursor: null };
const boardPage: WorkBoardPage = {
  columns: { todo: [boardItem] },
  next_cursor: null,
};
const hierarchy: WorkHierarchyFrame = {
  kind: "hierarchy",
  nodes: [],
  truncated: false,
};
const agendaFrame: WorkFrame = {
  kind: "agenda",
  filters: {},
  page: agendaPage,
};
const created: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Ring Anna fredag",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  domain_id: null,
};

function fakeTransport() {
  const mocks = {
    getWorkAgenda: vi.fn().mockResolvedValue(agendaPage),
    getWorkBoard: vi.fn().mockResolvedValue(boardPage),
    getWorkHierarchy: vi.fn().mockResolvedValue(hierarchy),
    listUnsortedTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listDomains: vi.fn().mockResolvedValue([]),
    listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listSavedWorkViews: vi.fn().mockResolvedValue([]),
    createTask: vi.fn().mockResolvedValue({ task: created }),
    updateTask: vi.fn().mockResolvedValue({
      task: { ...agendaItem, status: "completed", version: 2 },
    }),
  };
  const total = () =>
    Object.values(mocks).reduce((sum, mock) => sum + mock.mock.calls.length, 0);
  return { mocks, transport: mocks as unknown as WorkTransport, total };
}

type Props = Partial<React.ComponentProps<typeof WorkFullscreen>>;

function shell(transport: WorkTransport, props: Props = {}) {
  return (
    <WorkFullscreen
      transport={transport}
      labels={workEn}
      shellLabels={workShellLabelsEn}
      {...props}
    />
  );
}

/** Lets pending reads answer and their state land. */
async function settle() {
  await act(async () => {
    await new Promise((resolve) => setTimeout(resolve, 0));
    await new Promise((resolve) => setTimeout(resolve, 0));
  });
}

describe("Work shell reads", () => {
  it("(i) a hidden room without a result reads nothing; shown, it reads its first tab and the To sort count once", async () => {
    const fake = fakeTransport();
    const { rerender } = render(shell(fake.transport, { active: false }));
    await settle();
    console.info("[perf] work shell hidden: calls =", fake.total());
    expect(fake.total()).toBe(0);

    rerender(shell(fake.transport, { active: true }));
    await settle();
    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    console.info("[perf] work shell shown: calls =", {
      agenda: fake.mocks.getWorkAgenda.mock.calls.length,
      unsorted: fake.mocks.listUnsortedTasks.mock.calls.length,
      savedViews: fake.mocks.listSavedWorkViews.mock.calls.length,
      board: fake.mocks.getWorkBoard.mock.calls.length,
    });
    expect(fake.mocks.getWorkAgenda).toHaveBeenCalledTimes(1);
    expect(fake.mocks.listUnsortedTasks).toHaveBeenCalledTimes(1);
    expect(fake.mocks.getWorkBoard).not.toHaveBeenCalled();
    expect(fake.mocks.getWorkHierarchy).not.toHaveBeenCalled();
  });

  it("(i) the To sort count is read once when active and a new refreshKey arrive together", async () => {
    const fake = fakeTransport();
    const { rerender } = render(
      shell(fake.transport, { initial: agendaFrame, active: false }),
    );
    await settle();
    expect(fake.total()).toBe(0);

    rerender(
      shell(fake.transport, {
        initial: agendaFrame,
        active: true,
        refreshKey: 1,
      }),
    );
    await settle();
    expect(fake.mocks.listUnsortedTasks).toHaveBeenCalledTimes(1);
  });

  it("(ii) a write in the shell reads the tab that is not shown only when it is pressed, once", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    render(shell(fake.transport, { initial: agendaFrame }));
    await settle();
    await user.click(screen.getByRole("button", { name: "Status" }));
    expect(await screen.findByText("Board-uppgift")).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: "Agenda" }));
    await settle();
    expect(fake.mocks.getWorkBoard).toHaveBeenCalledTimes(1);

    // A write of the Agenda while the Agenda is shown: the Board is out of date, the Agenda holds the change itself.
    await user.click(
      screen.getByRole("button", { name: "Mark Agenda-uppgift as done" }),
    );
    await waitFor(() => expect(fake.mocks.updateTask).toHaveBeenCalledTimes(1));
    await settle();
    console.info("[perf] work write from the agenda: board reads =", {
      boardAfterWrite: fake.mocks.getWorkBoard.mock.calls.length - 1,
    });
    expect(fake.mocks.getWorkBoard).toHaveBeenCalledTimes(1);

    await user.click(screen.getByRole("button", { name: "Status" }));
    await settle();
    expect(fake.mocks.getWorkBoard).toHaveBeenCalledTimes(2);

    // Pressed again with no new write: no read.
    await user.click(screen.getByRole("button", { name: "Agenda" }));
    await user.click(screen.getByRole("button", { name: "Status" }));
    await settle();
    expect(fake.mocks.getWorkBoard).toHaveBeenCalledTimes(2);
  });

  it("(iii) the same Task answered twice is listed once in 'Just added'", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    render(shell(fake.transport, { initial: agendaFrame }));
    const agenda = await screen.findByRole("region", { name: "Agenda" });
    await user.click(screen.getByRole("button", { name: "New task" }));
    const field = within(agenda).getByRole("textbox", { name: "New task" });

    // Two titles; the server answers both with the Task it already made (a retry that replayed the result).
    await user.type(field, "Ring Anna fredag{Enter}");
    await waitFor(() => expect(fake.mocks.createTask).toHaveBeenCalledTimes(1));
    await within(agenda).findByRole("region", { name: "Just added (1)" });
    await user.type(
      within(agenda).getByRole("textbox", { name: "New task" }),
      "Ring Anna igen{Enter}",
    );
    await waitFor(() => expect(fake.mocks.createTask).toHaveBeenCalledTimes(2));
    await settle();

    const group = within(agenda).getByRole("region", { name: /Just added/ });
    console.info(
      "[perf] work same Task answered twice: rows in 'Just added' =",
      within(group).getAllByRole("listitem").length,
    );
    expect(group).toHaveAccessibleName("Just added (1)");
    expect(within(group).getAllByRole("listitem")).toHaveLength(1);
  });

  it("(iv) the saved views list is not read at mount; opening the panel reads it once, for both bars", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    render(shell(fake.transport, { initial: agendaFrame }));
    await settle();
    // Both bars (Agenda and Board) are mounted, but a bar reads its list only when its panel opens.
    console.info(
      "[perf] work saved views reads at mount =",
      fake.mocks.listSavedWorkViews.mock.calls.length,
    );
    expect(fake.mocks.listSavedWorkViews).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    await user.click(
      screen.getByRole("button", { name: savedViewsLabelsEn.button }),
    );
    await settle();
    console.info(
      "[perf] work saved views reads after opening the panel =",
      fake.mocks.listSavedWorkViews.mock.calls.length,
    );
    expect(fake.mocks.listSavedWorkViews).toHaveBeenCalledTimes(1);
    expect(fake.mocks.listSavedWorkViews).toHaveBeenCalledWith(false);
  });
});
