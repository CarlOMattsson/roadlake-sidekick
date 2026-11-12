import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { AgendaView } from "@/features/work-app/agenda";
import { hierarchyDetailLabelsEn } from "@/features/work-app/hierarchy-detail-labels";
import { workEn } from "@/features/work-app/labels";
import { newTaskInputLabelsEn } from "@/features/work-app/new-task-input-labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport";
import { WorkFullscreen } from "@/features/work-app/work-fullscreen";
import { WorkView } from "@/features/work-app/work-view";
import { workShellLabelsEn } from "@/features/work-app/work-shell-labels";
import { toolOffered } from "@/features/mcp-apps/tool-support";
import { CompanionRoomTransport } from "@/mobile/companion-transport";
import { fakeNative, ok } from "./helpers/fake-native";

/*
 * The Work room shows only the write controls whose tool the host answers (RoomTransport.supportsTool and
 * .supportsCall). The host here is the real CompanionRoomTransport's closed list over a fake plugin, so the tests follow
 * what the Android app answers; the views run in jsdom, which is not a real Claude or Android host. A host without the
 * questions (Claude) keeps every control.
 */

afterEach(cleanup);

const companion = new CompanionRoomTransport(fakeNative(() => ok({})));
/** What the Android app's transport answers: reads, complete, update_task only for the tick, the Step tick. */
const APP = {
  supportsTool: companion.supportsTool,
  supportsCall: companion.supportsCall,
};

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const task: WorkTask = {
  id: TASK_ID,
  title: "Ring Anna om flytten",
  status: "todo",
  due_at: "2026-11-08T22:59:00.000Z",
  version: 1,
};
const done: WorkTask = { ...task, status: "completed" };
const step = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  title: "Boka flyttbil",
  status: "todo",
  due_at: null,
  version: 1,
};
const contact = {
  id: "019f0000-0000-7000-8000-0000000000f1",
  display_name: "Anna Exempel",
  version: 1,
};

function detailTransport(
  support: Partial<WorkTransport>,
  shown: WorkTask = task,
): WorkTransport {
  return {
    ...support,
    getTask: vi.fn().mockResolvedValue({ task: shown }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [contact], next_cursor: null }),
    listTaskSteps: vi
      .fn()
      .mockResolvedValue({ items: [step], next_cursor: null }),
    listTaskExternalReferences: vi.fn().mockResolvedValue({
      items: [
        {
          id: "r1",
          kind: "email",
          provider: "x",
          account_ref: "a",
          external_id: "e",
          instance_ref: "i",
          title: "Offertmejlet",
          url: null,
          occurs_at: null,
        },
      ],
      next_cursor: null,
    }),
  } as unknown as WorkTransport;
}

async function renderDetail(
  support: Partial<WorkTransport>,
  shown: WorkTask = task,
) {
  render(
    <WorkView
      transport={detailTransport(support, shown)}
      initial={{ kind: "task", id: TASK_ID }}
      labels={workEn}
    />,
  );
  await screen.findByText(step.title);
  await screen.findByText(contact.display_name);
}

describe("the Task detail where the host writes only the tick", () => {
  it("keeps every control when the host names no tools (Claude)", async () => {
    await renderDetail({});
    expect(screen.getByRole("button", { name: /^Change date/ })).toBeVisible();
    expect(
      screen.getByRole("button", {
        name: new RegExp(`^${hierarchyDetailLabelsEn.changeStatus}`),
      }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: workEn.markDone })).toBeVisible();
    expect(
      screen.getByRole("button", { name: workEn.moreActions }),
    ).toBeVisible();
    expect(screen.getByRole("button", { name: workEn.addStep })).toBeVisible();
    expect(
      screen.getByRole("button", { name: workEn.linkContact }),
    ).toBeVisible();
    expect(screen.getByRole("checkbox")).toBeVisible();
    expect(
      screen.getByRole("button", { name: /Remove .*Offertmejlet/ }),
    ).toBeVisible();
    // The title edits on a tap.
    await userEvent.click(
      screen.getByRole("heading", { name: task.title, level: 2 }),
    );
    expect(await screen.findByRole("form")).toBeVisible();
  });

  it("keeps only 'Mark as done' and the Step tick of the writes, and shows contacts and links read-only", async () => {
    await renderDetail(APP);
    expect(screen.getByRole("button", { name: workEn.markDone })).toBeVisible();
    // The read-only parts stay.
    expect(screen.getByText(step.title)).toBeVisible();
    expect(screen.getByText(contact.display_name)).toBeVisible();
    expect(screen.getByText("Offertmejlet")).toBeVisible();
    // The writes that are refused are not drawn.
    expect(screen.queryByRole("button", { name: /^Change date/ })).toBeNull();
    expect(screen.queryByRole("button", { name: /^Add date/ })).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: new RegExp(`^${hierarchyDetailLabelsEn.changeStatus}`),
      }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: workEn.moreActions }),
    ).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.addStep })).toBeNull();
    expect(
      screen.queryByRole("button", { name: workEn.linkContact }),
    ).toBeNull();
    // The Step tick is in the app: complete_task_step and the reopen of update_task_step are answered.
    expect(screen.getByRole("checkbox")).toBeVisible();
    expect(
      screen.queryByRole("button", { name: /Remove .*Offertmejlet/ }),
    ).toBeNull();
    expect(screen.queryByText(workEn.stepMenuHint)).toBeNull();
    // A tap on the title does not open the editor.
    await userEvent.click(
      screen.getByRole("heading", { name: task.title, level: 2 }),
    );
    expect(screen.queryByRole("form")).toBeNull();
  });

  it("draws an open Step as a dot and a done Step as a bare tick, text with its state, never a box or a checkbox", async () => {
    const doneStep = {
      ...step,
      id: "019f0000-0000-7000-8000-0000000000e2",
      title: "Ring flyttfirman",
      status: "completed",
    };
    // A host that does not answer the Step tick (here: the app's list without complete_task_step).
    const transport = detailTransport({
      ...APP,
      supportsTool: (name) =>
        name !== "complete_task_step" && companion.supportsTool(name),
    });
    transport.listTaskSteps = vi
      .fn()
      .mockResolvedValue({ items: [step, doneStep], next_cursor: null });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workEn}
      />,
    );
    await screen.findByText(doneStep.title);
    expect(screen.queryByRole("checkbox")).toBeNull();
    const list = screen.getByText(step.title).closest("ul") as HTMLElement;
    const open = within(list).getByRole("img", {
      name: workEn.taskStatus.todo,
    });
    const closed = within(list).getByRole("img", {
      name: workEn.taskStatus.completed,
    });
    expect(open.getAttribute("data-glyph")).toBe("step-read-dot");
    expect(closed.getAttribute("data-glyph")).toBe("step-read-check");
    // No frame: no square on either row.
    expect(list.querySelector("rect")).toBeNull();
  });

  it("offers 'Reopen' on a done Task, which the reopen route sets back to todo, and no status chip", async () => {
    await renderDetail(APP, done);
    expect(
      screen.getByRole("button", { name: workEn.reopenTask }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: workEn.markDone })).toBeNull();
    expect(
      screen.queryByRole("button", {
        name: new RegExp(`^${hierarchyDetailLabelsEn.changeStatus}`),
      }),
    ).toBeNull();
  });

  it("offers a control again when the host answers its tool", async () => {
    await renderDetail({
      supportsTool: () => true,
      supportsCall: (name) => name !== "update_task",
    });
    // update_task is refused whatever the change, but the step and contact tools are there.
    expect(screen.queryByRole("button", { name: /^Change date/ })).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.markDone })).toBeNull();
    expect(screen.getByRole("button", { name: workEn.addStep })).toBeVisible();
    expect(screen.getByRole("checkbox")).toBeVisible();
    // The Task's ⋯ is there for "Ta bort uppgift" (the trash tools are answered) but holds no Redigera, which
    // update_task refuses; the Contact's link is removed from its row's own menu.
    await userEvent.click(
      screen.getByRole("button", { name: workEn.moreActions }),
    );
    expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
    expect(
      screen.getByRole("button", { name: workEn.deleteTask }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /More options for Anna Exempel/ }),
    ).toBeInTheDocument();
  });
});

const overdue: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Betala fakturan",
  status: "todo",
  due_at: "2026-10-27T09:00:00.000Z",
  version: 3,
  agenda_group: "overdue",
};
const today: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c2",
  title: "Boka målare",
  status: "todo",
  due_at: null,
  version: 1,
  agenda_group: "today",
};

function renderAgenda(
  support: Partial<WorkTransport>,
  items: WorkItemRecord[] = [overdue, today],
) {
  const updateTask = vi.fn(
    (id: string, version: number, changes: WorkTaskChanges) =>
      Promise.resolve({
        task: {
          id,
          title: "",
          status: changes.status ?? "todo",
          due_at: null,
          version: version + 1,
        },
      }),
  );
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items, next_cursor: null },
  };
  render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={
        { ...support, updateTask, getTask: vi.fn() } as unknown as WorkTransport
      }
      labels={workEn}
      moves={0}
      onOpen={vi.fn()}
      now={new Date(2026, 9, 29, 10, 0)}
    />,
  );
  return { updateTask };
}

function rowOf(title: string): HTMLElement {
  const row = screen.getByRole("button", { name: title }).closest("li");
  if (!row) throw new Error(`no row for ${title}`);
  return row;
}

describe("the Agenda where the host writes only the tick", () => {
  it("keeps the quick choices, the move-all button and the tip when the host names no tools (Claude)", () => {
    renderAgenda({});
    expect(
      screen.getByRole("button", { name: workEn.moveAllOverdue(1) }),
    ).toBeVisible();
    expect(screen.getByText(workEn.rowMenuHint)).toBeVisible();
    fireEvent.contextMenu(rowOf(today.title));
    const row = within(rowOf(today.title));
    expect(row.getByRole("group", { name: workEn.status })).toBeVisible();
    expect(
      row.getByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeVisible();
    expect(
      row.getAllByRole("button", { name: /Mark .* (done|status)/i }).length,
    ).toBeGreaterThan(0);
  });

  it("offers only 'Done' in the quick choices, no dates, no move-all, and no Undo after the tick", async () => {
    const { updateTask } = renderAgenda(APP);
    expect(
      screen.queryByRole("button", { name: workEn.moveAllOverdue(1) }),
    ).toBeNull();
    // The tick stays, and the row's quick choices are the status group with Done only.
    fireEvent.contextMenu(rowOf(today.title));
    const row = within(rowOf(today.title));
    const status = within(row.getByRole("group", { name: workEn.status }));
    expect(
      status.getAllByRole("button").map((button) => button.textContent),
    ).toEqual([workEn.taskStatus.completed]);
    expect(
      row.queryByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeNull();
    // The tick writes the completing change and then names it, with an Undo that reopens the Task.
    await userEvent.click(
      within(rowOf(today.title)).getByRole("button", {
        name: `Mark ${today.title} as done`,
      }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({ status: "completed" });
    expect(await screen.findByText(workEn.agendaDoneInStatus)).toBeVisible();
    await userEvent.click(
      await screen.findByRole("button", { name: workEn.agendaUndo }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[1]?.[1]).toBe(2);
    expect(updateTask.mock.calls[1]?.[2]).toEqual({ status: "todo" });
  });

  it("offers no Undo when the tick left a status the reopen route does not set back to", async () => {
    renderAgenda(APP, [{ ...today, status: "in_progress" }]);
    await userEvent.click(
      within(rowOf(today.title)).getByRole("button", {
        name: `Mark ${today.title} as done`,
      }),
    );
    expect(await screen.findByText(workEn.agendaDoneInStatus)).toBeVisible();
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).toBeNull();
  });

  it("reopens a done row with its glyph, which writes todo", async () => {
    const { updateTask } = renderAgenda(APP, [
      { ...today, status: "completed" },
    ]);
    await userEvent.click(
      within(rowOf(today.title)).getByRole("button", {
        name: `Mark ${today.title} as not done`,
      }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({ status: "todo" });
  });

  it("offers an in-progress row only Done in its quick choices, no todo", () => {
    renderAgenda(APP, [{ ...today, status: "in_progress" }]);
    fireEvent.contextMenu(rowOf(today.title));
    const status = within(
      within(rowOf(today.title)).getByRole("group", { name: workEn.status }),
    );
    expect(
      status.getAllByRole("button").map((button) => button.textContent),
    ).toEqual([workEn.taskStatus.completed]);
  });
});

describe("the fullscreen tabs' + where the host cannot create a Task", () => {
  function mount(support: Partial<WorkTransport>) {
    const transport = {
      ...support,
      getWorkAgenda: vi
        .fn()
        .mockResolvedValue({ items: [today], next_cursor: null }),
      listUnsortedTasks: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    } as unknown as WorkTransport;
    render(
      <WorkFullscreen
        transport={transport}
        initial={{
          kind: "agenda",
          filters: {},
          page: { items: [today], next_cursor: null },
        }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
  }

  it("shows + without support questions (Claude)", async () => {
    mount({});
    expect(
      await screen.findByRole("button", { name: newTaskInputLabelsEn.field }),
    ).toBeVisible();
  });

  it("hides + when the host lacks create_task", async () => {
    mount(APP);
    await screen.findByText(today.title);
    expect(
      screen.queryByRole("button", { name: newTaskInputLabelsEn.field }),
    ).toBeNull();
  });
});

describe("the done line after a tick, with and without the Status tab", () => {
  async function tick(tabs?: ("agenda" | "board" | "hierarchy")[]) {
    const updateTask = vi.fn().mockResolvedValue({
      task: { ...today, title: "", status: "completed", version: 2 },
    });
    const transport = {
      ...APP,
      updateTask,
      getWorkAgenda: vi
        .fn()
        .mockResolvedValue({ items: [today], next_cursor: null }),
      listUnsortedTasks: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    } as unknown as WorkTransport;
    render(
      <WorkFullscreen
        transport={transport}
        initial={{
          kind: "agenda",
          filters: {},
          page: { items: [today], next_cursor: null },
        }}
        {...(tabs ? { tabs } : {})}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await userEvent.click(
      await screen.findByRole("button", {
        name: `Mark ${today.title} as done`,
      }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
  }

  it("points at Status when the host serves the Status tab (Claude)", async () => {
    await tick();
    expect(await screen.findByText(workEn.agendaDoneInStatus)).toBeVisible();
  });

  it("says only Done when the host serves no Status tab (the Android app)", async () => {
    await tick(["agenda"]);
    expect(await screen.findByText(workEn.taskStatus.completed)).toBeVisible();
    expect(screen.queryByText(workEn.agendaDoneInStatus)).toBeNull();
  });
});

describe("toolOffered", () => {
  it("answers true without questions, and follows the call when the host names it", () => {
    expect(toolOffered(undefined, "update_task")).toBe(true);
    expect(toolOffered({}, "update_task", { changes: {} })).toBe(true);
    expect(toolOffered(APP, "update_task")).toBe(true);
    expect(
      toolOffered(APP, "update_task", { changes: { status: "completed" } }),
    ).toBe(true);
    expect(
      toolOffered(APP, "update_task", { changes: { status: "todo" } }),
    ).toBe(false);
    expect(
      toolOffered(APP, "update_task", {
        changes: { status: "todo" },
        from_status: "completed",
      }),
    ).toBe(true);
    expect(toolOffered(APP, "create_task")).toBe(false);
    expect(toolOffered(APP, "get_task", { task_id: TASK_ID })).toBe(true);
  });
});
