import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import {
  isStandIn,
  useQueuedRecords,
} from "@/features/work-app/shared/use-queued-records";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  TASK_ID,
  task,
  other,
  makeTransport,
  rowOf,
  resetAgendaEnvironment,
} from "@tests/helpers/agenda-view-fixtures";
import {
  projectA,
  rootProject,
  rootTask,
  taskA,
  transport as fakeTransport,
} from "@tests/helpers/work-app-fixtures";

/*
 * "Väntar…" for a Task or Project whose write waits in the phone's outbox (its edit, or its own making). The views run
 * in jsdom with a simulated host; this is not a real Android or Claude host.
 */

afterEach(resetAgendaEnvironment);

type Offline = NonNullable<WorkTransport["offline"]>;

/** A transport with the phone's outbox: `waiting` are the ids of records with a write still to send. */
function withOutbox(base: WorkTransport, waiting: string[]) {
  const listeners: Array<() => void> = [];
  const queuedRecordIds = vi.fn(() =>
    Promise.resolve(new Set(waiting.map((id) => id.toLowerCase()))),
  );
  const offline: Offline = {
    readAt: vi.fn(() => undefined),
    queuedRecordIds,
    onQueueChanged: vi.fn((listener: () => void) => {
      listeners.push(listener);
      return () => undefined;
    }),
  };
  return {
    transport: { ...base, offline } as WorkTransport,
    queuedRecordIds,
    emit: () => listeners.forEach((listener) => listener()),
  };
}

function renderAgenda(
  items: WorkItemRecord[],
  work: WorkTransport,
  labels = workEn,
) {
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: {},
    page: { items, next_cursor: null },
  };
  return render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={work}
      labels={labels}
      moves={0}
      onOpen={vi.fn()}
    />,
  );
}

it("reads the ids waiting in the outbox, and again when a run of the outbox ends", async () => {
  const { transport, queuedRecordIds, emit } = withOutbox(fakeTransport(), [
    "ABC",
  ]);
  const { result } = renderHook(() => useQueuedRecords(transport, "page"));
  expect(result.current.size).toBe(0);
  await waitFor(() => expect(result.current).toEqual(new Set(["abc"])));
  const reads = queuedRecordIds.mock.calls.length;
  act(() => emit());
  await waitFor(() =>
    expect(queuedRecordIds.mock.calls.length).toBeGreaterThan(reads),
  );
});

it("is empty without an outbox (Claude) and when the read fails", async () => {
  const { result } = renderHook(() =>
    useQueuedRecords(fakeTransport(), "page"),
  );
  expect(result.current.size).toBe(0);
  const failing = withOutbox(fakeTransport(), []);
  failing.queuedRecordIds.mockRejectedValue(new Error("no"));
  const failed = renderHook(() => useQueuedRecords(failing.transport, "page"));
  await waitFor(() => expect(failing.queuedRecordIds).toHaveBeenCalled());
  expect(failed.result.current.size).toBe(0);
});

it("knows a stand-in id from a server id", () => {
  expect(isStandIn("queued-7f3a")).toBe(true);
  expect(isStandIn("QUEUED-7f3a")).toBe(true);
  expect(isStandIn(TASK_ID)).toBe(false);
});

it("draws Waiting… in the meta line of an agenda Task that waits, and on no other row", async () => {
  const { transport } = withOutbox(makeTransport().transport, [TASK_ID]);
  renderAgenda([task, other], transport);
  const row = rowOf(task.title);
  await waitFor(() =>
    expect(within(row).getByText(workEn.queued)).toHaveClass("sk-queued"),
  );
  expect(within(row).getByRole("button", { name: /Mark/ })).toBeEnabled();
  expect(within(rowOf(other.title)).queryByText(workEn.queued)).toBeNull();
});

it("words the agenda mark in Swedish and gives a tick precedence over it", async () => {
  const { transport } = withOutbox(makeTransport().transport, [TASK_ID]);
  const ticked = {
    ...transport,
    offline: {
      ...transport.offline!,
      queuedCompletions: () => Promise.resolve(new Set([TASK_ID])),
    },
  } as WorkTransport;
  renderAgenda([task], ticked, workSv);
  const row = rowOf(task.title);
  await waitFor(() =>
    expect(within(row).getByText(workSv.sending)).toBeVisible(),
  );
  expect(within(row).queryByText(workSv.queued)).toBeNull();
  expect(workSv.queued).toBe("Väntar…");
});

it("blocks the tick of a Task made offline, whose stand-in the server does not know", async () => {
  const standIn: WorkItemRecord = { ...task, id: "queued-abc123" };
  const { transport } = withOutbox(makeTransport().transport, [standIn.id]);
  renderAgenda([standIn], transport);
  const row = rowOf(standIn.title);
  await waitFor(() =>
    expect(within(row).getByText(workEn.queued)).toBeVisible(),
  );
  expect(within(row).getByRole("button", { name: /Mark/ })).toBeDisabled();
});

it("draws no mark in the agenda in Claude, where the transport has no outbox", () => {
  renderAgenda([task], makeTransport().transport);
  expect(screen.queryByText(workEn.queued)).toBeNull();
});

it("says under a Task's title that its write waits, and not for another Task", async () => {
  const { transport } = withOutbox(fakeTransport(), [taskA.id]);
  const { unmount } = render(rootTask(transport));
  const mark = await screen.findByText(workEn.queued);
  expect(mark).toHaveClass("sk-queued");
  expect(mark.closest("p")).toHaveClass("work-task-meta");
  unmount();
  const none = withOutbox(fakeTransport(), ["something-else"]).transport;
  render(rootTask(none));
  await screen.findByText(taskA.title);
  expect(screen.queryByText(workEn.queued)).toBeNull();
});

it("says under a Project's title that its edit waits", async () => {
  const { transport } = withOutbox(fakeTransport(), [projectA.id]);
  render(rootProject(transport));
  const mark = await screen.findByText(workEn.queued);
  expect(mark).toHaveClass("sk-queued");
});
