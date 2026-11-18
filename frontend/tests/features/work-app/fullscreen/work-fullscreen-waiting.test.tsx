import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import { workEn } from "@/features/work-app/shared/labels";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";
import type {
  WorkAgendaPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

const waitingItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Svar från Anders om bildformat",
  status: "todo",
  version: 2,
  due_at: null,
  agenda_group: "overdue",
  waiting: true,
  waiting_since: "2026-11-13T09:00:00+01:00",
  waiting_on_contact_name: "Anders",
};
const todayItem: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Dagens uppgift",
  status: "todo",
  version: 1,
  due_at: null,
  agenda_group: "today",
};
const agendaPage: WorkAgendaPage = { items: [todayItem], next_cursor: null };

function fakeTransport() {
  const getWorkAgenda = vi.fn().mockResolvedValue(agendaPage);
  const getWorkBoard = vi
    .fn()
    .mockResolvedValue({ columns: { todo: [] }, next_cursor: null });
  const listUnsortedTasks = vi
    .fn()
    .mockResolvedValue({ items: [], next_cursor: null });
  return {
    transport: {
      getWorkAgenda,
      getWorkBoard,
      listUnsortedTasks,
      listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
      listDomains: vi.fn().mockResolvedValue([]),
    } as unknown as WorkTransport,
    getWorkAgenda,
  };
}

describe("the Agenda tab after the waiting view was shown", () => {
  it("opens the dated agenda again, also after another tab was visited", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    render(
      <WorkFullscreen
        transport={fake.transport}
        initial={{
          kind: "agenda",
          filters: { waiting: "waiting" },
          page: { items: [waitingItem], next_cursor: null },
        }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    expect(screen.getByText("Waiting on · 1")).toBeInTheDocument();
    expect(fake.getWorkAgenda).not.toHaveBeenCalled();

    await user.click(screen.getByRole("button", { name: "Status" }));
    await user.click(screen.getByRole("button", { name: "Agenda" }));

    expect(await screen.findByText("Dagens uppgift")).toBeInTheDocument();
    expect(fake.getWorkAgenda).toHaveBeenCalledWith({});
    expect(screen.queryByText("Waiting on · 1")).toBeNull();
  });

  it("leaves a dated agenda alone when the tab is pressed again", async () => {
    const fake = fakeTransport();
    const user = userEvent.setup();
    render(
      <WorkFullscreen
        transport={fake.transport}
        initial={{
          kind: "agenda",
          filters: {},
          page: agendaPage,
        }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Status" }));
    await user.click(screen.getByRole("button", { name: "Agenda" }));
    await waitFor(() =>
      expect(screen.getByText("Dagens uppgift")).toBeInTheDocument(),
    );
    expect(fake.getWorkAgenda).not.toHaveBeenCalled();
  });
});
