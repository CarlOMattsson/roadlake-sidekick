import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  hierarchyDetailLabelsEn,
  hierarchyDetailLabelsSv,
} from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { TaskSummaryList } from "@/features/work-app/tasks/task-summary-list";
import type {
  WorkTaskSummary,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  projectA,
  transport as fakeTransport,
} from "@tests/helpers/work-app-fixtures";

/* A Project's and a Process's Tasks: the open ones by due date, the completed ones in a closed "Klara (n)" fold, and a
   tag every Task has said once above the list instead of on each row. A simulated host only. */

function task(
  id: string,
  title: string,
  due_at: string | null,
  status = "todo",
  tags: string[] = [],
): WorkTaskSummary {
  return { id, title, status, due_at, tags };
}

const tasks = [
  task("t-none", "Utan datum", null, "todo", ["kund", "intern"]),
  task("t-done", "Klar sak", "2026-10-01T22:59:00Z", "completed", ["kund"]),
  task("t-late", "Försenad sak", "2020-01-02T22:59:00Z", "todo", [
    "kund",
    "brådskande",
  ]),
  task("t-soon", "Snart sak", "2999-11-26T22:59:00Z", "todo", ["kund"]),
];

function renderProject(
  items: WorkTaskSummary[],
  more: string | null = null,
  labels = workSv,
) {
  const transport: WorkTransport = fakeTransport({
    getProject: vi.fn().mockResolvedValue({ project: projectA }),
    listProjectTasks: vi.fn().mockResolvedValue({ items, next_cursor: more }),
  });
  return render(
    <WorkView
      transport={transport}
      initial={{ kind: "project", id: projectA.id }}
      labels={labels}
    />,
  );
}

function rowTitles(): string[] {
  return screen
    .getAllByRole("listitem")
    .map((row) => row.querySelector(".work-agenda-body button")?.textContent)
    .filter((title): title is string => Boolean(title));
}

describe("the Tasks of a Project page", () => {
  it("orders the open Tasks, overdue first, dated by day, undated last, and folds the completed ones", async () => {
    renderProject(tasks);
    await screen.findByText("Försenad sak");
    expect(rowTitles()).toEqual(["Försenad sak", "Snart sak", "Utan datum"]);
    const fold = screen.getByRole("button", { name: /^Klara/ });
    expect(fold).toHaveTextContent("Klara (1)");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByText("Klar sak")).toBeNull();
    await userEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(await screen.findByText("Klar sak")).toBeInTheDocument();
    // The completed Task is last, after the open ones.
    expect(rowTitles().at(-1)).toBe("Klar sak");
  });

  it("words the fold in English", async () => {
    renderProject(tasks, null, workEn);
    expect(
      await screen.findByRole("button", { name: /^Done/ }),
    ).toHaveTextContent("Done (1)");
  });

  it("has no fold when no Task is completed", async () => {
    renderProject(tasks.filter((item) => item.status !== "completed"));
    await screen.findByText("Försenad sak");
    expect(screen.queryByRole("button", { name: /^Klara/ })).toBeNull();
  });

  it("says the tag every Task has once above the list, and keeps the others on their rows", async () => {
    renderProject(tasks);
    await screen.findByText("Försenad sak");
    const line = screen.getByText(hierarchyDetailLabelsSv.onAllTasks);
    expect(line.closest("p")).toHaveTextContent("kund");
    const rows = screen.getAllByRole("listitem");
    // `kund` is on every row's data but drawn on none of the open rows; `b` stays on the row that has it.
    for (const row of rows) expect(row).not.toHaveTextContent("kund");
    const late = rows.find((row) => within(row).queryByText("Försenad sak"));
    expect(late).toHaveTextContent("brådskande");
  });

  it("words the shared tag line in English", async () => {
    renderProject(tasks, null, workEn);
    expect(
      await screen.findByText(hierarchyDetailLabelsEn.onAllTasks),
    ).toBeInTheDocument();
  });

  it("keeps every tag on its row when no tag is on every Task", async () => {
    renderProject([
      task("a", "Första", null, "todo", ["kund"]),
      task("b", "Andra", null, "todo", ["intern"]),
    ]);
    await screen.findByText("Första");
    expect(screen.queryByText(hierarchyDetailLabelsSv.onAllTasks)).toBeNull();
    const first = screen.getAllByRole("listitem")[0];
    expect(first).toHaveTextContent("kund");
  });

  it("does not claim a shared tag while more Tasks are still to load", async () => {
    renderProject(tasks, "cursor-2");
    await screen.findByText("Försenad sak");
    expect(screen.queryByText(hierarchyDetailLabelsSv.onAllTasks)).toBeNull();
  });
});

describe("the shared task list", () => {
  it("keeps its order and every tag on its rows without hideTags", () => {
    render(
      <TaskSummaryList
        tasks={[
          task("a", "Först", null, "todo", ["kund", "x"]),
          task("b", "Sist", null, "todo", ["kund"]),
        ]}
        labels={workSv}
        empty="Tomt"
        onOpen={vi.fn()}
      />,
    );
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Först");
    expect(rows[0]).toHaveTextContent("kund");
    expect(rows[1]).toHaveTextContent("kund");
  });

  it("leaves the listed tags off the rows with hideTags", () => {
    render(
      <TaskSummaryList
        tasks={[task("a", "Först", null, "todo", ["kund", "x"])]}
        labels={workSv}
        empty="Tomt"
        onOpen={vi.fn()}
        hideTags={["kund"]}
      />,
    );
    const row = screen.getByRole("listitem");
    expect(row).not.toHaveTextContent("kund");
    expect(row).toHaveTextContent("x");
  });
});
