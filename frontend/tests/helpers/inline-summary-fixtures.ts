import path from "node:path";
import { afterEach, beforeEach, vi } from "vitest";
import { type WorkItemRecord } from "@/features/work-app/transport";

export const srcDir = path.resolve(
  import.meta.dirname,
  "../../src/features/work-app",
);

export const agendaItems: WorkItemRecord[] = [
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a1",
    title: "Betala faktura",
    status: "todo",
    due_at: "2026-10-20T09:00:00Z",
    agenda_group: "overdue",
  },
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a2",
    title: "Ring Anna",
    status: "todo",
    due_at: "2026-10-21T09:00:00Z",
    agenda_group: "overdue",
  },
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a3",
    title: "Skriv offerten",
    status: "in_progress",
    due_at: "2026-10-25T15:00:00Z",
    agenda_group: "today",
  },
  {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000a4",
    title: "Städa garaget",
    status: "todo",
    due_at: "2026-11-02T09:00:00Z",
    agenda_group: "upcoming",
  },
];

/** Fixed clock (25 Oct 2026, Europe/Stockholm) so relative due labels are stable. Call once at the top of a test file. */
export function installFixedClock(): void {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-10-25T12:00:00Z"));
  });

  afterEach(() => {
    vi.useRealTimers();
  });
}
