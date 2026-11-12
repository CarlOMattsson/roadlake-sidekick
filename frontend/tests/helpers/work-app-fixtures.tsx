import { act, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { vi, type Mock } from "vitest";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn } from "@/features/work-app/shared/labels";
import {
  type WorkBoardPage,
  type WorkContactRecord,
  type WorkFilters,
  type WorkItemRecord,
  type WorkProject,
  type WorkStep,
  type WorkTask,
  type WorkTaskSummary,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

export const taskA = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: "2026-10-30T09:00:00Z",
  version: 1,
};

export const taskB = {
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Skicka faktura",
  status: "doing",
  due_at: null,
  version: 1,
};

export const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

/** Full Contact records: get_contact_context and the contact writes return these fields. */
export const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: "anna@example.test",
  phone: "+46 70 000 00 01",
  context_note: "Vill ha offerten före fredag.",
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

export const bo: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c2",
  display_name: "Bo Berg",
  email: null,
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

export const annaTasks: WorkTaskSummary[] = [
  { id: taskB.id, title: taskB.title, status: taskB.status, due_at: null },
];

export const taskC: WorkTaskSummary = {
  id: "019f0000-0000-7000-8000-0000000000a3",
  title: "Boka möte",
  status: "todo",
  due_at: null,
};

export const projectA: WorkProject = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Offert till Anna",
  status: "active",
  description: "Första utkastet",
  start_date: "2026-10-01",
  target_date: "2026-11-15",
  version: 1,
};

/** A Task that belongs to projectA, so the Task view shows the Project button. */
export const projectTask: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a4",
  title: "Skriv offertutkast",
  status: "in_progress",
  due_at: null,
  version: 1,
  project_id: projectA.id,
};

export function transport(
  overrides: Partial<WorkTransport> = {},
): WorkTransport {
  return {
    getTask: vi.fn((id: string) =>
      Promise.resolve({
        task:
          [taskA, taskB, projectTask].find((task) => task.id === id) ?? taskA,
      }),
    ),
    getProject: vi.fn().mockResolvedValue({ project: projectA }),
    updateProject: vi.fn().mockResolvedValue({
      project: { ...projectA, version: 2 },
    }),
    listProjectTasks: vi.fn().mockResolvedValue({
      items: [
        {
          id: projectTask.id,
          title: projectTask.title,
          status: projectTask.status,
          due_at: null,
        },
      ],
      next_cursor: null,
    }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [anna], next_cursor: null }),
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: annaTasks, next_cursor: null },
    }),
    updateTask: vi.fn().mockResolvedValue({ task: { ...taskA, version: 2 } }),
    rescheduleTasks: vi.fn().mockResolvedValue({ count: 0 }),
    reorderBoardColumn: vi.fn().mockResolvedValue({ items: [] }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listUnsortedTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listDomains: vi.fn().mockResolvedValue([]),
    completeTaskStep: vi.fn(),
    updateTaskStep: vi.fn(),
    createTask: vi.fn().mockResolvedValue({ task: newTask }),
    createTaskStep: vi.fn().mockResolvedValue({ step: newStep }),
    searchContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    createContact: vi.fn().mockResolvedValue({ contact: bo }),
    linkContactToTask: vi.fn().mockResolvedValue({ linked: true }),
    unlinkContactFromTask: vi.fn().mockResolvedValue({ linked: false }),
    trashTask: vi.fn().mockResolvedValue({ version: 7 }),
    restoreTask: vi.fn().mockResolvedValue({}),
    getWorkBoard: vi.fn().mockResolvedValue({ columns: {}, next_cursor: null }),
    getWorkAgenda: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    getWorkHierarchy: vi.fn(),
    archiveTaskStep: vi.fn(),
    restoreTaskStep: vi.fn(),
    reorderTaskSteps: vi.fn(),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    archiveStepAction: vi.fn(),
    restoreStepAction: vi.fn(),
    reorderStepActions: vi.fn(),
    listProcessTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listSavedWorkViews: vi.fn().mockResolvedValue([]),
    createSavedWorkView: vi.fn(),
    updateSavedWorkView: vi.fn(),
    archiveSavedWorkView: vi.fn(),
    restoreSavedWorkView: vi.fn(),
    linkContactToProject: vi.fn().mockResolvedValue({ linked: true }),
    unlinkContactFromProject: vi.fn().mockResolvedValue({ linked: false }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    unlinkExternalReferenceFromTask: vi.fn(),
    linkExternalReferenceToTask: vi.fn(),
    getDomain: vi.fn(),
    getProcess: vi.fn(),
    updateContact: vi
      .fn()
      .mockResolvedValue({ contact: { ...anna, version: 2 } }),
    addContactAlias: vi
      .fn()
      .mockResolvedValue({ contact: { ...anna, version: 2 } }),
    removeContactAlias: vi
      .fn()
      .mockResolvedValue({ contact: { ...anna, version: 2 } }),
    archiveContact: vi
      .fn()
      .mockResolvedValue({ contact: { ...anna, archived: true, version: 2 } }),
    restoreContact: vi
      .fn()
      .mockResolvedValue({ contact: { ...anna, version: 2 } }),
    ...overrides,
  };
}

export const stepId = "019f0000-0000-7000-8000-0000000000b1";

export const step: WorkStep = {
  id: stepId,
  title: "Skriv offerten",
  status: "todo",
  due_at: null,
  version: 3,
};

/** The Task create_task returns for projectA, and the Step create_task_step returns. */
export const newTask: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  title: "Ring leverantören",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: projectA.id,
};

export const newStep: WorkStep = {
  id: "019f0000-0000-7000-8000-0000000000b2",
  title: "Boka tid",
  status: "todo",
  due_at: null,
  version: 1,
};

/** The key argument of a write mock call, checked for shape where the test is about keys. */
export function keyOf(mock: Mock, call: number): unknown {
  return (mock.mock.calls[call] as unknown[]).at(-1);
}

export function rootTask(work: WorkTransport, id = taskA.id) {
  return (
    <WorkView transport={work} initial={{ kind: "task", id }} labels={workEn} />
  );
}

export function rootProject(work: WorkTransport, id = projectA.id) {
  return (
    <WorkView
      transport={work}
      initial={{ kind: "project", id }}
      labels={workEn}
    />
  );
}

/**
 * Opens the editor of the Task or Contact in view: there is no pen, so Edit is the first entry of the ⋯ menu on the
 * heading row (a tap on the title also edits, but the menu is what keyboard and tests use).
 */
export async function openEdit(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
  await user.click(await screen.findByRole("button", { name: workEn.edit }));
}

/* Board, move and agenda */

export const boardTask: WorkItemRecord = {
  kind: "task",
  id: taskA.id,
  title: taskA.title,
  status: "todo",
  due_at: taskA.due_at,
  version: 1,
};

export const boardTaskB: WorkItemRecord = {
  kind: "task",
  id: taskC.id,
  title: taskC.title,
  status: "todo",
  due_at: null,
  version: 1,
};

export const boardDoing: WorkItemRecord = {
  kind: "task",
  id: projectTask.id,
  title: projectTask.title,
  status: "in_progress",
  due_at: null,
  version: 1,
  project_id: projectA.id,
};

export const boardProject: WorkItemRecord = {
  kind: "project",
  id: projectA.id,
  title: projectA.title,
  status: "active",
  due_at: null,
  version: 1,
};

export const boardDomain: WorkItemRecord = {
  kind: "domain",
  id: "019f0000-0000-7000-8000-0000000000f1",
  title: "Hushållet",
  status: "paused",
  due_at: null,
  version: 1,
};

export const boardPage: WorkBoardPage = {
  columns: {
    todo: [boardTask, boardTaskB],
    in_progress: [boardDoing],
    completed: [],
    active: [boardProject],
    paused: [boardDomain],
  },
  next_cursor: null,
};

/** The board after taskA moved to In progress, as get_work_board returns it. */
export const movedPage: WorkBoardPage = {
  columns: {
    todo: [boardTaskB],
    in_progress: [
      { ...boardTask, status: "in_progress", version: 2 },
      boardDoing,
    ],
    completed: [],
    active: [boardProject],
    paused: [boardDomain],
  },
  next_cursor: null,
};

export const agendaTask: WorkItemRecord = {
  ...boardTask,
  agenda_group: "overdue",
};

/** Opens a board card's quick choices from the keyboard: focus on its title, then Shift+F10. */
export async function openBoardGroup(
  user: ReturnType<typeof userEvent.setup>,
  title: string,
) {
  act(() => screen.getByRole("button", { name: title }).focus());
  await user.keyboard("{Shift>}{F10}{/Shift}");
}

export function rootBoard(
  work: WorkTransport,
  page: WorkBoardPage = boardPage,
  filters: WorkFilters = {},
  labels = workEn,
) {
  return (
    <WorkView
      transport={work}
      initial={{ kind: "board", filters, page }}
      labels={labels}
    />
  );
}

export function contactRoot(work: WorkTransport, labels = workEn) {
  return (
    <WorkView
      transport={work}
      initial={{ kind: "contact", id: anna.id }}
      labels={labels}
    />
  );
}

/** Opens the ⋯ menu on the Contact's heading row, where Archive and Restore are. */
export async function openMoreMenu(user: ReturnType<typeof userEvent.setup>) {
  await user.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
}
