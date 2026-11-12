import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  manageLabelsEn,
  manageLabelsSv,
} from "@/features/work-app/manage-labels";
import { workEn, workSv, type WorkLabels } from "@/features/work-app/labels";
import { AUTO_STEP_PAGES, readSteps } from "@/features/work-app/step-pages";
import { TaskSteps } from "@/features/work-app/task-steps";
import type { WorkStep, WorkTransport } from "@/features/work-app/transport";

// jsdom has no CSS global; the row controls use CSS.escape to find a control by its Step id.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";

function stepAt(index: number): WorkStep {
  return {
    id: `019f0000-0000-7000-8000-${String(index).padStart(12, "0")}`,
    title: `Steg ${index}`,
    status: "todo",
    due_at: null,
    version: 1,
    position: index,
  };
}

/** `count` Steps served in pages of `size`, the cursor being the index the next page starts at. */
function pagedSteps(count: number, size = 100) {
  const all = Array.from({ length: count }, (_, index) => stepAt(index));
  return vi.fn((_taskId: string, cursor?: string) => {
    const from = cursor ? Number(cursor) : 0;
    const to = Math.min(from + size, count);
    return Promise.resolve({
      items: all.slice(from, to),
      next_cursor: to < count ? String(to) : null,
    });
  });
}

function transportWith(listTaskSteps: ReturnType<typeof vi.fn>) {
  const work = {
    listTaskSteps,
    reorderTaskSteps: vi.fn(),
    archiveTaskStep: vi.fn(),
    restoreTaskStep: vi.fn(),
    completeTaskStep: vi.fn(),
    updateTaskStep: vi.fn(),
    createTaskStep: vi.fn(),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  };
  return { work, transport: work as unknown as WorkTransport };
}

function renderSteps(transport: WorkTransport, labels: WorkLabels = workSv) {
  return render(
    <TaskSteps taskId={TASK_ID} transport={transport} labels={labels} />,
  );
}

describe("readSteps", () => {
  it("follows next_cursor to the last page and returns every Step once, in order", async () => {
    const list = pagedSteps(250);

    const read = await readSteps(
      (cursor) => list(TASK_ID, cursor),
      () => true,
    );

    expect(list.mock.calls.map(([, cursor]) => cursor)).toEqual([
      undefined,
      "100",
      "200",
    ]);
    expect(read?.items.map((step: WorkStep) => step.id)).toEqual(
      Array.from({ length: 250 }, (_, index) => stepAt(index).id),
    );
    expect(read).toMatchObject({ cursor: undefined, failed: false });
  });

  it("stops after the page limit and hands back the cursor to continue from", async () => {
    const list = pagedSteps(1500);

    const read = await readSteps(
      (cursor) => list(TASK_ID, cursor),
      () => true,
    );

    expect(list).toHaveBeenCalledTimes(AUTO_STEP_PAGES);
    expect(read?.items).toHaveLength(1000);
    expect(read?.cursor).toBe("1000");
  });

  it("keeps the pages read when a later page fails, and throws when the first does", async () => {
    const later = vi
      .fn()
      .mockResolvedValueOnce({ items: [stepAt(0)], next_cursor: "1" })
      .mockRejectedValueOnce(new Error("offline"));
    const kept = await readSteps(later, () => true);
    expect(kept).toEqual({
      items: [stepAt(0)],
      cursor: "1",
      failed: true,
    });

    await expect(
      readSteps(vi.fn().mockRejectedValue(new Error("offline")), () => true),
    ).rejects.toThrow("offline");
  });

  it("returns nothing once the caller has moved on", async () => {
    const list = pagedSteps(250);
    let current = true;
    const read = readSteps(
      async (cursor) => {
        const page = await list(TASK_ID, cursor);
        current = false;
        return page;
      },
      () => current,
    );
    expect(await read).toBeUndefined();
    expect(list).toHaveBeenCalledTimes(1);
  });
});

describe("TaskSteps with more than one page of Steps", () => {
  it("reads every page and draws all 120 Steps without a Show more button", async () => {
    const { work, transport } = transportWith(pagedSteps(120));

    renderSteps(transport);

    expect(
      await screen.findByRole("checkbox", { name: "Steg 119" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(120);
    expect(work.listTaskSteps).toHaveBeenNthCalledWith(1, TASK_ID, undefined);
    expect(work.listTaskSteps).toHaveBeenNthCalledWith(2, TASK_ID, "100");
    expect(
      screen.queryByRole("button", { name: workSv.stepsShowMore }),
    ).not.toBeInTheDocument();
    // The count is true again: every Step is held.
    expect(screen.getByRole("heading", { name: workSv.stepsProgress(0, 120) }));
  });

  it.each([
    ["sv", workSv, manageLabelsSv],
    ["en", workEn, manageLabelsEn],
  ])(
    "(%s) offers Show more steps when a later page fails, adds the page on click and then moves again",
    async (_locale, labels, manage) => {
      const user = userEvent.setup();
      const list = pagedSteps(60, 30);
      const good = list.getMockImplementation()!;
      // The first read gets page one and then fails on page two; Show more succeeds.
      list.mockImplementationOnce(good);
      list.mockImplementationOnce(() => Promise.reject(new Error("offline")));
      const { work, transport } = transportWith(list);
      work.reorderTaskSteps.mockResolvedValue({ items: [] });

      renderSteps(transport, labels);

      expect(await screen.findByRole("alert", {})).toHaveTextContent(
        labels.stepsReadMoreFailed,
      );
      expect(screen.getAllByRole("checkbox")).toHaveLength(30);
      // A reorder needs every Step, so the move buttons wait.
      fireEvent.contextMenu(
        screen.getByRole("checkbox", { name: "Steg 1" }).closest("li")!,
      );
      expect(
        screen.queryByRole("button", { name: manage.moveDownFor("Steg 1") }),
      ).not.toBeInTheDocument();

      await user.click(
        screen.getByRole("button", { name: labels.stepsShowMore }),
      );

      expect(
        await screen.findByRole("checkbox", { name: "Steg 59" }),
      ).toBeInTheDocument();
      expect(screen.getAllByRole("checkbox")).toHaveLength(60);
      expect(work.listTaskSteps).toHaveBeenLastCalledWith(TASK_ID, "30");
      expect(
        screen.queryByRole("button", { name: labels.stepsShowMore }),
      ).not.toBeInTheDocument();
      await waitFor(() =>
        expect(screen.queryByRole("alert")).not.toBeInTheDocument(),
      );
      // The row menu is still open, and now offers the move.
      expect(
        screen.getByRole("button", { name: manage.moveDownFor("Steg 1") }),
      ).toBeInTheDocument();
    },
  );

  it("says so and keeps the list when Show more fails, and the button tries again", async () => {
    const user = userEvent.setup();
    const list = pagedSteps(25, 2);
    const good = list.getMockImplementation()!;
    const { transport } = transportWith(list);
    renderSteps(transport);
    const button = await screen.findByRole("button", {
      name: workSv.stepsShowMore,
    });
    expect(screen.getAllByRole("checkbox")).toHaveLength(20);

    list.mockImplementationOnce(() => Promise.reject(new Error("offline")));
    await user.click(button);
    expect(await screen.findByRole("alert")).toHaveTextContent(
      workSv.stepsReadMoreFailed,
    );
    expect(screen.getAllByRole("checkbox")).toHaveLength(20);

    list.mockImplementation(good);
    await user.click(
      screen.getByRole("button", { name: workSv.stepsShowMore }),
    );
    expect(
      await screen.findByRole("checkbox", { name: "Steg 21" }),
    ).toBeInTheDocument();
    expect(screen.getAllByRole("checkbox")).toHaveLength(22);
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });
});
