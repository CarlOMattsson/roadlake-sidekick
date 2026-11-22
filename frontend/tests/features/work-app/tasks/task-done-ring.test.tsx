import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it } from "vitest";

import {
  RoomSurfaceContext,
  type RoomSurface,
} from "@/features/mcp-apps/ui/room-context";
import { workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import { KEY, taskA, transport } from "@tests/helpers/work-app-fixtures";

// Simulated host: the wide frame's split is stood in for by a RoomSurfaceContext with a `pane`. It is not a test in a
// real Claude or Android host.

function renderTask(surface?: Partial<RoomSurface>) {
  const work = transport();
  const view = (
    <WorkView
      transport={work}
      initial={{ kind: "task", id: taskA.id }}
      labels={workSv}
    />
  );
  render(
    surface ? (
      <RoomSurfaceContext.Provider
        value={{ active: true, framed: true, ...surface }}
      >
        {view}
      </RoomSurfaceContext.Provider>
    ) : (
      view
    ),
  );
  return work;
}

const title = () =>
  screen.findByRole("heading", { level: 2, name: taskA.title });

describe("a Task's done control beside its list", () => {
  it.each(["detail", "drawer"] as const)(
    "is the ring before the title in a %s pane, and no 'Markera klar' text button",
    async (pane) => {
      renderTask({ pane });

      const heading = await title();
      const ring = await screen.findByRole("button", {
        name: workSv.markDone,
      });
      expect(ring).toHaveClass("work-task-ring");
      expect(ring.textContent).toBe("");
      // The ring stands on the title's line, before it.
      const row = heading.closest(".work-detail-title-row");
      expect(row).not.toBeNull();
      expect(row).toContainElement(ring);
      expect(
        ring.compareDocumentPosition(heading) &
          Node.DOCUMENT_POSITION_FOLLOWING,
      ).toBeTruthy();
      // The one control with that name is the ring: there is no text button next to it.
      expect(screen.getAllByRole("button", { name: workSv.markDone })).toEqual([
        ring,
      ]);
      expect(ring.querySelector("svg")).not.toBeNull();
    },
  );

  it("marks the Task done with the ring, the same write as the button", async () => {
    const user = userEvent.setup();
    const work = renderTask({ pane: "detail" });

    await user.click(
      await screen.findByRole("button", { name: workSv.markDone }),
    );

    await waitFor(() => expect(work.updateTask).toHaveBeenCalledTimes(1));
    expect(work.updateTask).toHaveBeenCalledWith(
      taskA.id,
      1,
      { status: "completed" },
      expect.stringMatching(KEY),
    );
  });

  it.each([["no context"], ["a single pane"], ["a list pane"]])(
    "is the text button 'Markera klar' with %s, and no ring",
    async (name) => {
      renderTask(
        name === "no context"
          ? undefined
          : { pane: name === "a single pane" ? "single" : "list" },
      );

      const heading = await title();
      const button = await screen.findByRole("button", {
        name: workSv.markDone,
      });
      expect(button).toHaveTextContent(workSv.markDone);
      expect(button).not.toHaveClass("work-task-ring");
      expect(document.querySelector(".work-task-ring")).toBeNull();
      expect(heading.closest(".work-detail-title-row")).toBeNull();
    },
  );
});
