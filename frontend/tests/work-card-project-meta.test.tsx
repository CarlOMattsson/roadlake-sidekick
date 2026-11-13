import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { RecordMeta } from "@/features/work-app/shared/record-meta";
import { workDate } from "@/features/mcp-apps/ui/due";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";

/*
 * The meta line of a record row is one builder, RecordMeta: "{due} · {status} · {kind} · {High} ·
 * {Project}", the Project last. The parts are separate elements in that fixed order, and the "·" between them is drawn
 * in CSS, so the DOM text has no separator. The board's Status groups by status, so there `inStatus` leaves the status
 * out. A Task's kind ("Uppgift", "Task") is not shown; a Project keeps its kind. A record without a part has no meta
 * line. The time is its own `.work-card-due` element; a Task due today has none under the group "Idag", but an overdue
 * time always stands. The agenda passes its `group`, which takes away only that time; the Project stands in the agenda
 * too.
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000b1";

/** The clock for relative due dates: 25 Oct 2026, so a due date on 30 Oct reads "Fri 30 Oct". */
const NOW = new Date("2026-10-25T12:00:00Z");

type MetaOptions = { group?: string | null; inStatus?: boolean };

function renderMeta(
  item: WorkItemRecord,
  labels: WorkLabels,
  options: MetaOptions = {},
) {
  return render(
    <RecordMeta
      item={item}
      labels={labels}
      now={NOW}
      group={options.group}
      inStatus={options.inStatus}
    />,
  ).container;
}

/** The text of each part of the meta line, in order; empty when the row has no meta line. */
function metaParts(
  item: WorkItemRecord,
  labels: WorkLabels,
  options: MetaOptions = {},
): string[] {
  const meta = renderMeta(item, labels, options).querySelector(
    ".work-card-meta",
  );
  return Array.from(meta?.children ?? [], (part) => part.textContent ?? "");
}

/** The class of each part of the meta line, in order: which element a part is. */
function metaClasses(item: WorkItemRecord, labels: WorkLabels): string[] {
  const meta = renderMeta(item, labels).querySelector(".work-card-meta");
  return Array.from(meta?.children ?? [], (part) => part.className);
}

describe("record meta names the Project of a Task, not its kind", () => {
  it("shows the Project title and no kind in Swedish", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Lämna deklarationen",
      status: "todo",
      project_id: "019f0000-0000-7000-8000-0000000000c1",
      project_title: "Bokslut och skatt",
    };
    expect(metaParts(item, workSv)).toEqual(["Bokslut och skatt"]);
    expect(metaParts(item, workSv)).not.toContain(workSv.kindName.task);
  });

  it("shows the Project title and no kind in English", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "File the tax return",
      status: "todo",
      project_id: "019f0000-0000-7000-8000-0000000000c1",
      project_title: "Year-end and tax",
    };
    expect(metaParts(item, workEn)).toEqual(["Year-end and tax"]);
  });

  it("has no meta line for a Task that names no Project and has no due date", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Fristående",
      status: "todo",
      project_id: null,
      project_title: null,
    };
    expect(
      renderMeta(item, workSv).querySelector(".work-card-meta"),
    ).toBeNull();
  });

  it("keeps the kind of a Project record", () => {
    const item: WorkItemRecord = {
      kind: "project",
      id: "019f0000-0000-7000-8000-0000000000d1",
      title: "Kök",
      status: "active",
      due_at: "2026-10-30",
    };
    expect(metaParts(item, workEn)).toEqual(["Fri 30 Oct", "Project"]);
  });

  it("on the board a Project shows its own status and not its kind: its section already says Projekt", () => {
    const item: WorkItemRecord = {
      kind: "project",
      id: "019f0000-0000-7000-8000-0000000000d2",
      title: "Kök",
      status: "active",
      due_at: null,
    };
    expect(metaParts(item, workSv, { inStatus: true })).toEqual(["Aktivt"]);
    expect(
      metaParts({ ...item, status: "paused" }, workEn, { inStatus: true }),
    ).toEqual(["Paused"]);
  });

  it("gives the Project name the Project's own element, which the board cuts with its title", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "todo",
      project_title: "Bokslut och skatt",
    };
    const project = renderMeta(item, workEn).querySelector(
      ".work-card-meta > .work-card-project",
    );
    expect(project).toHaveAttribute("title", "Bokslut och skatt");
  });
});

describe("record meta shows only the parts the record has", () => {
  /** A part never carries a separator of its own: the "·" is drawn in CSS between the parts. */
  function expectNoSeparatorText(parts: string[]) {
    for (const part of parts) {
      expect(part).not.toContain("·");
    }
  }

  it("shows the due date and the Project of a blocked Task, and no status words on the board", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Vänta på leverans",
      status: "blocked",
      due_at: "2026-10-30T09:00:00Z",
      project_title: "Year-end and tax",
    };
    expect(metaParts(item, workEn, { inStatus: true })).toEqual([
      "Fri 30 Oct",
      "Year-end and tax",
    ]);
  });

  it("names the status between the date and the Project, outside the board", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Vänta på leverans",
      status: "blocked",
      due_at: "2026-10-30T09:00:00Z",
      project_title: "Year-end and tax",
    };
    expect(metaParts(item, workEn)).toEqual([
      "Fri 30 Oct",
      "Blocked",
      "Year-end and tax",
    ]);
    expect(metaClasses(item, workEn)).toEqual([
      "work-card-due",
      "work-card-status",
      "work-card-project",
    ]);
  });

  it("shows only the due date, without a separator, when a blocked Task has no Project", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Vänta på leverans",
      status: "blocked",
      due_at: "2026-10-30T09:00:00Z",
      project_title: null,
    };
    const parts = metaParts(item, workEn, { inStatus: true });
    expect(parts).toEqual(["Fri 30 Oct"]);
    expectNoSeparatorText(parts);
  });

  it("has no meta line when a blocked Task has neither a Project nor a valid due date, on the board", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Vänta på leverans",
      status: "blocked",
      due_at: "not-a-date",
    };
    const container = renderMeta(item, workEn, { inStatus: true });
    expect(container.querySelector(".work-card-meta")).toBeNull();
  });

  it("shows the Project and no due part for a completed Task", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Klar",
      status: "completed",
      due_at: "2026-10-30T09:00:00Z",
      project_title: "Year-end and tax",
    };
    expect(metaParts(item, workEn)).toEqual(["Year-end and tax"]);
  });

  it("shows a due date further away as its date, in its own time element with the full date as title", () => {
    const value = "2026-12-01T09:00:00Z";
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Betala skatten",
      status: "todo",
      due_at: value,
    };
    const container = renderMeta(item, workEn);
    const due = container.querySelector(".work-card-meta > .work-card-due");
    const time = due?.querySelector("time");
    expect(time).toHaveAttribute("datetime", value);
    expect(time).toHaveAttribute("data-tone", "later");
    expect(time).toHaveAttribute(
      "title",
      workDate(value, NOW, workEn.dateLocale, { relative: false }),
    );
    expect(time?.textContent).toBe(
      workDate(value, NOW, workEn.dateLocale, { inline: true }),
    );
  });

  it("gives the parts one fixed order, the time first, then the status, the High marker and the Project last, each in its own element, with no separator text", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "in_progress",
      project_title: "Kök",
      priority: "high",
      due_at: "2026-10-30T09:00:00Z",
    };
    expect(metaParts(item, workEn)).toEqual([
      "Fri 30 Oct",
      workEn.taskStatus.in_progress,
      "High",
      "Kök",
    ]);
    expect(metaClasses(item, workEn)).toEqual([
      "work-card-due",
      "work-card-status",
      "work-card-priority",
      "work-card-project",
    ]);
    expectNoSeparatorText(metaParts(item, workEn));
  });

  it("shows no time under the group Idag for a Task due today, but keeps its Project there and an overdue time", () => {
    const today: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "todo",
      project_title: "Kök",
      due_at: "2026-10-25T09:00:00Z",
    };
    // With the agenda's group: no time for today, but the Project stands. Without a group the time shows too.
    expect(metaParts(today, workEn, { group: "today" })).toEqual(["Kök"]);
    expect(metaParts(today, workEn)).toEqual(["Today", "Kök"]);
    const overdue: WorkItemRecord = {
      ...today,
      due_at: "2026-10-23T09:00:00Z",
    };
    expect(metaParts(overdue, workEn, { group: "today" })).toEqual([
      "2 days overdue",
      "Kök",
    ]);
  });

  it("shows the Project in the agenda's group as well as on the board's Status, last", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "todo",
      project_title: "Kök",
      due_at: "2026-10-30T09:00:00Z",
    };
    expect(metaParts(item, workEn, { group: "today" })).toEqual([
      "Fri 30 Oct",
      "Kök",
    ]);
    expect(metaParts(item, workEn, { inStatus: true })).toEqual([
      "Fri 30 Oct",
      "Kök",
    ]);
  });
});

describe("record meta shows an overdue Task as red text under its title, with no pill", () => {
  it("names the days in words, singular for one day", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "todo",
      due_at: "2026-10-23T09:00:00Z",
    };
    const container = renderMeta(item, workEn);
    const due = container.querySelector(".work-card-due time");
    expect(due?.textContent).toBe("2 days overdue");
    expect(due?.getAttribute("data-tone")).toBe("overdue");
    expect(metaParts({ ...item, due_at: "2026-10-24" }, workEn)).toEqual([
      "1 day overdue",
    ]);
  });

  it("uses the Swedish wording in Swedish", () => {
    const item: WorkItemRecord = {
      kind: "task",
      id: TASK_ID,
      title: "Ring Anna",
      status: "todo",
      due_at: "2026-10-20T09:00:00Z",
    };
    expect(metaParts(item, workSv)).toEqual(["5 dagar försenad"]);
  });
});

describe("record meta marks only a high-priority Task", () => {
  const base: WorkItemRecord = {
    kind: "task",
    id: TASK_ID,
    title: "Ring Anna",
    status: "todo",
    project_title: "Year-end and tax",
  };

  it("shows the High marker before the Project in Swedish", () => {
    expect(
      metaParts({ ...base, project_title: "Kök", priority: "high" }, workSv),
    ).toEqual(["Hög", "Kök"]);
  });

  it("shows the High marker after the due date and before the Project", () => {
    expect(
      metaParts(
        { ...base, priority: "high", due_at: "2026-10-30T09:00:00Z" },
        workEn,
      ),
    ).toEqual(["Fri 30 Oct", "High", "Year-end and tax"]);
  });

  it("shows the marker alone when a high-priority Task has no Project", () => {
    expect(
      metaParts({ ...base, project_title: null, priority: "high" }, workEn),
    ).toEqual(["High"]);
  });

  it("shows no marker for normal, low or urgent priority", () => {
    for (const priority of ["low", "normal", "urgent"]) {
      expect(metaParts({ ...base, priority }, workEn)).toEqual([
        "Year-end and tax",
      ]);
    }
  });
});

describe("record meta of a row in the group Idag", () => {
  it("keeps the status words of an in-progress Task but shows no date when it is due today", () => {
    const container = renderMeta(
      {
        kind: "task",
        id: TASK_ID,
        title: "Boka målare",
        status: "in_progress",
        due_at: "2026-10-25T09:00:00Z",
      },
      workEn,
      { group: "today" },
    );
    expect(container.querySelector(".work-card-status")?.textContent).toBe(
      "In progress",
    );
    expect(container.querySelector(".work-card-due")).toBeNull();
    expect(container.querySelector("time")).toBeNull();
  });
});
