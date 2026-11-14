import { cleanup, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import { workEn } from "@/features/work-app/shared/labels";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import type { WorkTransport } from "@/features/work-app/transport/transport";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";

/** The views the host serves are the room's `availableViews`; a view it does not serve is neither offered nor read. */
const agendaPage = { items: [], next_cursor: null };

function fake() {
  const getWorkAgenda = vi.fn().mockResolvedValue(agendaPage);
  const getWorkBoard = vi
    .fn()
    .mockResolvedValue({ columns: {}, next_cursor: null });
  const getWorkHierarchy = vi
    .fn()
    .mockResolvedValue({ kind: "hierarchy", nodes: [], truncated: false });
  const listUnsortedTasks = vi
    .fn()
    .mockResolvedValue({ items: [], next_cursor: null });
  return {
    getWorkAgenda,
    getWorkBoard,
    getWorkHierarchy,
    transport: {
      getWorkAgenda,
      getWorkBoard,
      getWorkHierarchy,
      listUnsortedTasks,
      listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
      listDomains: vi.fn().mockResolvedValue([]),
    } as unknown as WorkTransport,
  };
}

afterEach(cleanup);

describe("WorkFullscreen with a limited set of views", () => {
  it("offers all three tabs when the host lists none (the MCP App)", async () => {
    render(
      <WorkFullscreen
        transport={fake().transport}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: workEn.agenda });
    for (const name of ["Agenda", "Status", "Projects"])
      expect(screen.getByRole("button", { name })).toBeInTheDocument();
  });

  it("hides the tabs the host cannot serve", async () => {
    const f = fake();
    render(
      <WorkFullscreen
        transport={f.transport}
        tabs={["agenda", "board"]}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: workEn.agenda });
    expect(screen.getByRole("button", { name: "Status" })).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Projects" })).toBeNull();
    expect(f.getWorkHierarchy).not.toHaveBeenCalled();
  });

  it("shows no tab strip when one view is left, and never reads the others", async () => {
    const f = fake();
    render(
      <WorkFullscreen
        transport={f.transport}
        tabs={["agenda"]}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: workEn.agenda });
    for (const name of ["Agenda", "Status", "Projects"])
      expect(screen.queryByRole("button", { name })).toBeNull();
    expect(
      screen.queryByRole("group", { name: workShellLabelsEn.tabsLabel }),
    ).toBeNull();
    // The tools of the row stay: search and the "⋯" menu.
    expect(
      screen.getByRole("button", { name: workShellLabelsEn.search }),
    ).toBeInTheDocument();
    expect(f.getWorkBoard).not.toHaveBeenCalled();
    expect(f.getWorkHierarchy).not.toHaveBeenCalled();
  });

  it("falls back to the first listed tab when the first frame or start tab is unavailable", async () => {
    const f = fake();
    render(
      <WorkFullscreen
        transport={f.transport}
        tabs={["agenda"]}
        startTab="hierarchy"
        initial={{
          kind: "board",
          filters: {},
          page: { columns: {}, next_cursor: null },
        }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: workEn.agenda });
    expect(f.getWorkAgenda).toHaveBeenCalled();
    expect(f.getWorkBoard).not.toHaveBeenCalled();
  });

  it("keeps the tools of an offered tab working when another is hidden", async () => {
    const user = userEvent.setup();
    render(
      <WorkFullscreen
        transport={fake().transport}
        tabs={["agenda", "hierarchy"]}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: workEn.agenda });
    await user.click(screen.getByRole("button", { name: "Projects" }));
    expect(
      await screen.findByRole("button", {
        name: workShellLabelsEn.searchProjects,
      }),
    ).toBeInTheDocument();
  });
});
