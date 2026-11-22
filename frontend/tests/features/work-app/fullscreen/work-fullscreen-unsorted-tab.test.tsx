import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, onTestFinished, vi } from "vitest";

import {
  RoomSurfaceContext,
  type RoomSurface,
} from "@/features/mcp-apps/ui/room-context";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import { workEn } from "@/features/work-app/shared/labels";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";
import type {
  WorkAgendaPage,
  WorkFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// A simulated host: the shell's wide frame is stood in for by a RoomSurfaceContext with a `headSlot` element. It is
// not a test in a real Claude or Android host.

const agendaPage: WorkAgendaPage = {
  items: [
    {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000a1",
      title: "Agenda-uppgift",
      status: "todo",
      due_at: null,
      version: 1,
      project_id: null,
      agenda_group: "today",
    },
  ],
  next_cursor: null,
};
const agendaFrame: WorkFrame = {
  kind: "agenda",
  filters: {},
  page: agendaPage,
};

const unsortedTasks: WorkTask[] = [
  {
    id: "019f0000-0000-7000-8000-0000000000c1",
    title: "Köp ny dammsugare",
    status: "todo",
    due_at: null,
    version: 1,
    domain_id: null,
  },
  {
    id: "019f0000-0000-7000-8000-0000000000c2",
    title: "Ring försäkringsbolaget",
    status: "todo",
    due_at: null,
    version: 1,
    domain_id: null,
  },
];

function fakeTransport(): WorkTransport {
  return {
    getWorkAgenda: vi.fn().mockResolvedValue(agendaPage),
    getWorkBoard: vi.fn().mockResolvedValue({ columns: {}, next_cursor: null }),
    getWorkHierarchy: vi.fn().mockResolvedValue({
      kind: "hierarchy",
      nodes: [],
      truncated: false,
      tasks: [],
    }),
    listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listUnsortedTasks: vi
      .fn()
      .mockResolvedValue({ items: unsortedTasks, next_cursor: null }),
    listDomains: vi.fn().mockResolvedValue([]),
  } as unknown as WorkTransport;
}

function mount(surface: Partial<RoomSurface>) {
  return render(
    <RoomSurfaceContext.Provider
      value={{ active: true, framed: true, ...surface }}
    >
      <WorkFullscreen
        transport={fakeTransport()}
        initial={agendaFrame}
        labels={workEn}
        shellLabels={workShellLabelsEn}
        onRoute={vi.fn()}
      />
    </RoomSurfaceContext.Provider>,
  );
}

/** The shell's one-row head, as a wide frame has it; it leaves the document when the test is done. */
function wideHead() {
  const headSlot = document.createElement("div");
  document.body.append(headSlot);
  onTestFinished(() => headSlot.remove());
  return headSlot;
}

// jsdom joins a nested span to its label without the space ("Unsorted2"); a browser keeps it.
const TAB_NAME = "Unsorted 2";
const tab = () => screen.queryByRole("button", { name: TAB_NAME });
const row = () => screen.queryByRole("button", { name: "Unsorted (2)" });

describe("WorkFullscreen: To sort as a tab in a wide frame", () => {
  it("offers the tab 'Unsorted 2' and no row after the agenda when the frame has a head slot", async () => {
    mount({ headSlot: wideHead() });

    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    await waitFor(() => expect(tab()).toBeInTheDocument());
    expect(row()).not.toBeInTheDocument();
  });

  it("opens the triage list from the tab", async () => {
    const user = userEvent.setup();
    mount({ headSlot: wideHead() });

    await user.click(await screen.findByRole("button", { name: TAB_NAME }));

    expect(await screen.findByText("Köp ny dammsugare")).toBeVisible();
    expect(screen.getByText("Ring försäkringsbolaget")).toBeVisible();
    expect(
      document.querySelector("ul[data-triage]"),
      "the tab's list is the triage list",
    ).not.toBeNull();
  });

  it("keeps the row after the agenda, and no tab, without a head slot", async () => {
    mount({});

    expect(await screen.findByText("Agenda-uppgift")).toBeInTheDocument();
    await waitFor(() => expect(row()).toBeInTheDocument());
    expect(tab()).not.toBeInTheDocument();
  });
});
