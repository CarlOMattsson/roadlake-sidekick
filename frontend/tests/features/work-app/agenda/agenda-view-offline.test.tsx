import {
  agendaLabelsEn,
  agendaLabelsSv,
} from "@/features/work-app/agenda/agenda-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import { afterEach, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
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
  done,
  makeTransport,
  rowOf,
  resetAgendaEnvironment,
} from "@tests/helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

const STEP_ID = "019f0000-0000-7000-8000-0000000000c1";
const step: WorkItemRecord = {
  kind: "step",
  id: STEP_ID,
  title: "Mät fönstret",
  status: "todo",
  version: 1,
  task_id: done.id,
  due_at: null,
  agenda_group: "overdue",
};

type Offline = NonNullable<WorkTransport["offline"]>;

/** A transport with the phone's offline support: when the page was copied, and the ticks still in the outbox. */
function offlineTransport(copiedAt: number | null, queued: string[] = []) {
  const { transport, mock } = makeTransport();
  const listeners: Array<() => void> = [];
  const offline: Offline = {
    readAt: vi.fn(() => copiedAt ?? undefined),
    queuedCompletions: vi.fn(() =>
      Promise.resolve(new Set(queued.map((id) => id.toLowerCase()))),
    ),
    onQueueChanged: vi.fn((listener: () => void) => {
      listeners.push(listener);
      return () => undefined;
    }),
  };
  const withOffline = { ...transport, offline } as WorkTransport;
  return {
    transport: withOffline,
    mock,
    offline,
    emit: () => listeners.forEach((l) => l()),
  };
}

function renderWith(
  items: WorkItemRecord[],
  transport: WorkTransport,
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
      transport={transport}
      labels={labels}
      moves={0}
      onOpen={vi.fn()}
    />,
  );
}

it("says when the offline copy was read, in both languages, and nothing for a page the server answered", () => {
  // 08:05 on the owner's clock (Europe/Stockholm, UTC+1).
  const at = Date.parse("2026-11-12T07:05:00.000Z");
  const { transport } = offlineTransport(at);
  const { unmount } = renderWith([task], transport, workSv);
  const line = screen.getByText(/^Ingen anslutning · senast hämtad /);
  expect(line).toHaveAttribute("role", "status");
  expect(line).toHaveTextContent(/08[:.]05/);
  unmount();
  renderWith([task], offlineTransport(at).transport, workEn);
  expect(
    screen.getByText(/^No connection · last fetched .*08[:.]05/),
  ).toHaveClass("work-agenda-offline");
});

it("draws no offline line in Claude, where the transport has no offline support", () => {
  const { transport } = makeTransport();
  renderWith([task], transport);
  expect(document.querySelector(".work-agenda-offline")).toBeNull();
  expect(screen.queryByText(/No connection/)).toBeNull();
});

it("draws a tick that waits in the outbox as done, with Sending… for its meta line, and reads the outbox again when it runs", async () => {
  const { transport, offline, emit } = offlineTransport(null, [
    TASK_ID.toUpperCase(),
  ]);
  renderWith([task, other], transport);
  const row = rowOf(task.title);
  await waitFor(() =>
    expect(within(row).getByText(workEn.sending)).toHaveClass("sk-queued"),
  );
  expect(within(row).queryByRole("button", { name: /Mark/ })).toBeNull();
  expect(within(rowOf(other.title)).queryByText(workEn.sending)).toBeNull();
  const reads = vi.mocked(offline.queuedCompletions!).mock.calls.length;
  emit();
  await waitFor(() =>
    expect(
      vi.mocked(offline.queuedCompletions!).mock.calls.length,
    ).toBeGreaterThan(reads),
  );
});

it("counts only open Tasks in the overdue heading, not a Step or a tick still being sent", async () => {
  const { transport } = offlineTransport(null, [TASK_ID]);
  const second = {
    ...task,
    id: "019f0000-0000-7000-8000-0000000000a9",
    title: "Andra",
  };
  renderWith([task, second, step], transport, workSv);
  await waitFor(() =>
    expect(within(rowOf(task.title)).getByText(workSv.sending)).toBeVisible(),
  );
  const heading = screen.getByRole("heading", { name: /Försenade/ });
  expect(heading).toHaveTextContent(/1/);
  expect(heading).not.toHaveTextContent(/[23]/);
});

it("gives a Step its own muted square in the glyph column, and says the Task is done under a completed Task", () => {
  const { transport } = offlineTransport(null);
  renderWith([done, step], transport, workSv);
  const row = rowOf(step.title);
  const glyph = row.querySelector(".work-agenda-glyph-sub");
  expect(glyph).not.toBeNull();
  expect(glyph?.querySelector(".sk-status-glyph")).not.toBeNull();
  expect(row).toHaveAttribute("data-muted");
  expect(within(row).getByText(agendaLabelsSv.parentDone)).toBeVisible();
});

it("leaves a Step of an open Task unmuted, with its own meta", () => {
  const { transport } = offlineTransport(null);
  const open = { ...step, task_id: TASK_ID };
  renderWith([task, open], transport, workEn);
  const row = rowOf(open.title);
  expect(row).not.toHaveAttribute("data-muted");
  expect(within(row).queryByText(agendaLabelsEn.parentDone)).toBeNull();
});

it("has the offline words in both languages", () => {
  expect(workSv.sending).toBe("Skickas…");
  expect(workEn.sending).toBe("Sending…");
  expect(agendaLabelsSv.parentDone).toBe("Uppgiften är klar");
  expect(agendaLabelsEn.parentDone).toBe("Task done");
  expect(workSv.offlineCopy("08:05")).toContain("08:05");
  expect(workEn.offlineCopy("08:05")).toContain("08:05");
});
