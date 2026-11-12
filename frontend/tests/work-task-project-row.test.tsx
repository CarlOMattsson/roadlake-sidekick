import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { workSv } from "@/features/work-app/labels";
import { WorkView } from "@/features/work-app/work-view";
import type { WorkTask, WorkTransport } from "@/features/work-app/transport";

/*
 * The Task detail names its Project in the place chip ("Plats: Flytt"); the title the Task already carries is the
 * name, so get_project is read only when the link is followed. A host that cannot answer get_project (the Android
 * app's companion transport before it had a Project route) keeps the chip but offers no link to the Project. The
 * simulated transport here is not a real Claude or Android host.
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const PROJECT_ID = "019f0000-0000-7000-8000-0000000000c1";

const task: WorkTask = {
  id: TASK_ID,
  title: "Ring Anna om flytten",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: PROJECT_ID,
  project_title: "Flytt",
};

/** A transport whose get_project is refused, as the companion transport does for a tool outside its list. */
function transport(getProject: WorkTransport["getProject"]): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task }),
    getProject,
    listProjectTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    getWorkHierarchy: vi
      .fn()
      .mockResolvedValue({ kind: "hierarchy", nodes: [], truncated: false }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as WorkTransport;
}

function renderTask(
  workTransport: WorkTransport,
  supportsTool?: (name: string) => boolean,
) {
  return render(
    <WorkView
      transport={workTransport}
      initial={{ kind: "task", id: TASK_ID }}
      labels={workSv}
      supportsTool={supportsTool}
    />,
  );
}

describe("the place chip of a Task in a Project", () => {
  it("names the Project from the Task itself and reads get_project only when the link is followed", async () => {
    const user = userEvent.setup();
    const getProject = vi.fn().mockResolvedValue({
      project: { id: PROJECT_ID, title: "Flytt", status: "active", version: 1 },
    });
    renderTask(transport(getProject));

    const chip = await screen.findByRole("button", {
      name: "Ändra plats: Flytt",
    });
    expect(chip).toHaveTextContent("Plats: Flytt");
    expect(getProject).not.toHaveBeenCalled();

    await user.click(chip);
    await user.click(screen.getByRole("button", { name: "Öppna Flytt" }));
    expect(getProject).toHaveBeenCalledWith(PROJECT_ID);
  });

  it("offers no link and never reads the Project when the host lacks get_project", async () => {
    const user = userEvent.setup();
    const getProject = vi.fn();
    renderTask(transport(getProject), (name) => name !== "get_project");

    const chip = await screen.findByRole("button", {
      name: "Ändra plats: Flytt",
    });
    await user.click(chip);
    expect(
      screen.queryByRole("button", { name: "Öppna Flytt" }),
    ).not.toBeInTheDocument();
    expect(getProject).not.toHaveBeenCalled();
  });
});
