import { fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { BoardSummary } from "@/features/work-app/board/board-summary";
import { AgendaSummary } from "@/features/work-app/inline/inline-summary";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkAgendaPage,
  WorkBoardFrame,
  WorkBoardPage,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/** The open button's name is the label and, after " · ", what the card leaves out (§7), so match the start. */
const openBoardName = new RegExp(`^${workEn.openBoard}`);

const todoA: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const todoB: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b2",
  title: "Skicka faktura",
  status: "todo",
  due_at: null,
  version: 1,
};
const doing: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b3",
  title: "Boka möte med styrelsen",
  status: "in_progress",
  due_at: null,
  version: 1,
};
const done: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000b4",
  title: "Skriv offertutkast",
  status: "completed",
  due_at: null,
  version: 1,
};

/** Two To do, one In progress, no Blocked (absent column), one Done. */
const frame: WorkBoardFrame = {
  kind: "board",
  filters: {},
  page: {
    columns: {
      todo: [todoA, todoB],
      in_progress: [doing],
      completed: [done],
    },
    next_cursor: null,
  },
};

/**
 * Due Tasks for the nearest-due list. Dates are fixed in 2099 so the order never drifts. Open
 * Tasks in due order: dueSoon, dueMid, dueLater, dueFourth. doneEarly, noDue and the Project are
 * never listed; only the first three fit.
 */
const dueSoon: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Ring Anna om offerten",
  status: "in_progress",
  due_at: "2099-01-02T09:00:00+01:00",
  version: 1,
};
const dueMid: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c2",
  title: "Boka möte med styrelsen",
  status: "todo",
  due_at: "2099-01-05T00:00:00Z",
  version: 1,
};
const dueLater: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c3",
  title: "Skicka faktura",
  status: "todo",
  due_at: "2099-01-09",
  version: 1,
};
const dueFourth: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c4",
  title: "Vänta på leverans",
  status: "blocked",
  due_at: "2099-01-12",
  version: 1,
};
const doneEarly: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c5",
  title: "Skriv offertutkast",
  status: "completed",
  due_at: "2098-12-01",
  version: 1,
};
const noDue: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000c6",
  title: "Beställ skåp",
  status: "todo",
  due_at: null,
  version: 1,
};
const projectRecord: WorkItemRecord = {
  kind: "project",
  id: "019f0000-0000-7000-8000-0000000000c7",
  title: "Kök",
  status: "active",
  due_at: "2098-06-01",
  version: 1,
};

/** Three To do (one without a due date), one In progress, one Blocked, one Done, one Project. */
const dueFrame: WorkBoardFrame = {
  kind: "board",
  filters: {},
  page: {
    columns: {
      todo: [dueLater, noDue, dueMid],
      in_progress: [dueSoon],
      blocked: [dueFourth],
      completed: [doneEarly],
      active: [projectRecord],
    },
    next_cursor: null,
  },
};

/**
 * The page has a next cursor, and an `active` column holds a Project next to Tasks. Five records
 * on this page: two To do, one In progress, one Done and one Project.
 */
const cursorFrame: WorkBoardFrame = {
  kind: "board",
  filters: {},
  page: {
    columns: {
      todo: [todoA, todoB],
      in_progress: [doing],
      completed: [done],
      active: [projectRecord],
    },
    next_cursor: "019f0000-0000-7000-8000-0000000000e1",
  },
};

/** Only getWorkBoard could be reached from the board views; the rest is never called here. */
function workWithBoard(): WorkTransport {
  return {
    getWorkBoard: vi.fn().mockResolvedValue({ columns: {}, next_cursor: null }),
  } as unknown as WorkTransport;
}

it("shows a compact status summary inline, not the board", () => {
  render(
    <WorkView
      transport={workWithBoard()}
      initial={frame}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  expect(screen.getByRole("button", { name: openBoardName })).toBeVisible();
  // The counts bar legend names the three open statuses, zeros included, in column order. Done is not in the bar
  //: the summary counts what is still open.
  const legend = within(
    screen.getByRole("group", { name: workEn.status }),
  ).getByRole("list");
  expect(
    within(legend)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).toEqual(["To do2", "In progress1", "Blocked0"]);
  expect(legend).not.toHaveTextContent("Done");
  // No record titles inline: the board itself is not rendered.
  expect(screen.queryByRole("button", { name: todoA.title })).toBeNull();
  expect(screen.queryByText(todoA.title)).toBeNull();
});

it("shows the full board in fullscreen", () => {
  render(
    <WorkView transport={workWithBoard()} initial={frame} labels={workEn} />,
  );
  expect(
    screen.getByRole("heading", { level: 2, name: workEn.board }),
  ).toBeInTheDocument();
  expect(screen.getByRole("button", { name: todoA.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: openBoardName })).toBeNull();
});

it("shows the full board when the host cannot show fullscreen", () => {
  render(
    <WorkView
      transport={workWithBoard()}
      initial={frame}
      labels={workEn}
      fullscreen={undefined}
    />,
  );
  expect(screen.getByRole("button", { name: todoB.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: openBoardName })).toBeNull();
});

it("requests fullscreen when the summary's open-board action is pressed", async () => {
  const user = userEvent.setup();
  const fullscreen = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={frame}
      labels={workEn}
      fullscreen={fullscreen}
    />,
  );
  await user.click(screen.getByRole("button", { name: openBoardName }));
  expect(fullscreen).toHaveBeenCalledTimes(1);
});

it("switches from the summary to the board when the host goes fullscreen", () => {
  const fullscreen = vi.fn();
  const work = workWithBoard();
  const { rerender } = render(
    <WorkView
      transport={work}
      initial={frame}
      labels={workEn}
      fullscreen={fullscreen}
    />,
  );
  expect(screen.queryByRole("button", { name: todoA.title })).toBeNull();
  rerender(<WorkView transport={work} initial={frame} labels={workEn} />);
  expect(screen.getByRole("button", { name: todoA.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: openBoardName })).toBeNull();
});

it("sends the counts and column names once to the model context, never record titles", () => {
  const onModelContext = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={frame}
      labels={workEn}
      fullscreen={vi.fn()}
      onModelContext={onModelContext}
    />,
  );
  expect(onModelContext).toHaveBeenCalledTimes(1);
  const [summary] = onModelContext.mock.calls[0] as [string];
  expect(summary).toBe("Status: 2 to do, 1 in progress, 0 blocked, 1 done");
  for (const item of [todoA, todoB, doing, done]) {
    expect(summary).not.toContain(item.title);
  }
});

it("does not send model context when the board is shown in full", () => {
  const onModelContext = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={frame}
      labels={workEn}
      onModelContext={onModelContext}
    />,
  );
  expect(onModelContext).not.toHaveBeenCalled();
});

it("lists the three nearest open Tasks with a due date, nearest first", () => {
  const { container } = render(
    <WorkView
      transport={workWithBoard()}
      initial={dueFrame}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  // The rows are the agenda card's (InlineRow): the title on its own line, the status and the due words under it.
  const titles = Array.from(
    container.querySelectorAll(".work-compact-row-title"),
    (node) => node.textContent,
  );
  expect(titles).toEqual([dueSoon.title, dueMid.title, dueLater.title]);
  expect(
    container.querySelector(".work-compact-row .work-compact-row-meta"),
  ).toHaveTextContent("In progress");
  // The fourth due Task, the completed one, the one without a date and the Project stay out.
  for (const item of [dueFourth, doneEarly, noDue, projectRecord]) {
    expect(screen.queryByText(item.title)).toBeNull();
  }
});

it("sends counts only to the model context, never the due Task titles", () => {
  const onModelContext = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={dueFrame}
      labels={workEn}
      fullscreen={vi.fn()}
      onModelContext={onModelContext}
    />,
  );
  expect(onModelContext).toHaveBeenCalledTimes(1);
  const [summary] = onModelContext.mock.calls[0] as [string];
  expect(summary).toBe(
    "Status: 3 to do, 1 in progress, 1 blocked, 1 done; projects: 1",
  );
  for (const item of [dueSoon, dueMid, dueLater, dueFourth, doneEarly, noDue]) {
    expect(summary).not.toContain(item.title);
  }
});

it("counts the open Tasks in the legend, without Projects or Done, and says more exist with a next cursor", () => {
  const onModelContext = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={cursorFrame}
      labels={workEn}
      fullscreen={vi.fn()}
      onModelContext={onModelContext}
    />,
  );
  // The legend counts the open Tasks (three of the five records): the Done Task and the Project are not in it, and
  // the Project is a line of its own.
  const legend = within(
    screen.getByRole("group", { name: workEn.status }),
  ).getByRole("list");
  const total = within(legend)
    .getAllByRole("listitem")
    .reduce(
      (sum, item) => sum + Number(item.textContent?.match(/\d+$/)?.[0] ?? 0),
      0,
    );
  expect(total).toBe(
    Object.values(cursorFrame.page.columns)
      .flat()
      .filter((item) => item.kind === "task" && item.status !== "completed")
      .length,
  );
  expect(
    within(legend)
      .getAllByRole("listitem")
      .map((item) => item.textContent),
  ).not.toContain("Projects1");
  expect(screen.getByText("Projects: 1")).toBeInTheDocument();
  // The inline summary counts the open records the list does not show in one line: the three To do and In progress
  // Tasks (none has a due date, so none is listed). The Done Task is not open. The text to the model still says that
  // more records exist.
  expect(screen.getByText("· 3 more")).toHaveClass("work-compact-more");
  expect(screen.queryByText(workEn.boardMore)).toBeNull();
  const [summary] = onModelContext.mock.calls[0] as [string];
  expect(summary).toBe(
    "Status: 2 to do, 1 in progress, 0 blocked, 1 done, more not shown; projects: 1",
  );
});

it("says in one line how many Tasks the nearest-due list does not show", () => {
  const { container } = render(
    <WorkView
      transport={workWithBoard()}
      initial={dueFrame}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  // Five open Tasks: the three nearest with a due date are listed (dueSoon, dueMid, dueLater). Two are not: noDue
  // (To do, no due date) and dueFourth (Blocked). The Done Task is not open, so it is not counted. The summary has
  // one "2 more" aside on the open button instead of one line per status.
  expect(screen.getByText("· 2 more")).toHaveClass("work-compact-more");
  expect(
    screen.queryByText(/^\+\d+ (To do|Blocked|Done|In progress)$/),
  ).toBeNull();
  expect(container.querySelectorAll(".work-compact-more")).toHaveLength(1);
});

it("opens the board in fullscreen from its one action, which is no primary button", () => {
  const fullscreen = vi.fn();
  render(
    <WorkView
      transport={workWithBoard()}
      initial={dueFrame}
      labels={workEn}
      fullscreen={fullscreen}
    />,
  );
  const open = screen.getByRole("button", { name: openBoardName });
  // "Open Status" is the card's one action: the compact text button, not the ink (primary) button.
  expect(open).toHaveClass("sk-btn--open");
  expect(open).not.toHaveClass("sk-btn--primary");
  fireEvent.click(open);
  expect(fullscreen).toHaveBeenCalledTimes(1);
});

it("says more records exist when every loaded Task is listed but the page has a next cursor", () => {
  const listedAll: WorkBoardFrame = {
    kind: "board",
    filters: {},
    page: {
      columns: { todo: [dueMid], in_progress: [dueSoon] },
      next_cursor: "019f0000-0000-7000-8000-0000000000e2",
    },
  };
  render(
    <WorkView
      transport={workWithBoard()}
      initial={listedAll}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  expect(screen.getByText(`· ${workEn.boardMore}`)).toHaveClass(
    "work-compact-more",
  );
  expect(screen.queryByText(/^\+\d+ more$/)).toBeNull();
});

it("shows no +N when the list shows every record of each column", () => {
  const allShown: WorkBoardFrame = {
    kind: "board",
    filters: {},
    page: {
      columns: { todo: [dueMid], in_progress: [dueSoon] },
      next_cursor: null,
    },
  };
  const { container } = render(
    <WorkView
      transport={workWithBoard()}
      initial={allShown}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  expect(container.querySelectorAll(".work-compact-more")).toHaveLength(0);
});

/*
 * The inline board card (19): the kicker "Arbete · Status · ons 4 nov" and the title "2 overdue of 4 open",
 * and its rows carry the same meta as the agenda card (01) for the same Task.
 */
describe("the inline board card's kicker, title and row meta", () => {
  // Wednesday 4 November 2026, local time, so "ons 4 nov" and "Wed 4 Nov" are the day of the card.
  const WED = new Date(2026, 10, 4, 12, 0);

  function task(
    n: number,
    status: string,
    due_at: string | null,
    title = `Uppgift ${n}`,
  ): WorkItemRecord {
    return {
      kind: "task",
      id: `019f0000-0000-7000-8000-0000000001${String(n).padStart(2, "0")}`,
      title,
      status,
      due_at,
      version: 1,
    };
  }

  /** Four open Tasks, two of them overdue, and one done Task that is never counted. */
  const withOverdue: WorkBoardPage = {
    columns: {
      todo: [
        task(1, "todo", null),
        task(2, "todo", "2026-10-20T09:00:00+01:00"),
        task(3, "todo", "2026-10-21T09:00:00+01:00"),
      ],
      in_progress: [task(4, "in_progress", null)],
      completed: [task(5, "completed", "2026-10-01T09:00:00+01:00")],
    },
    next_cursor: null,
  };
  /** Three open Tasks, none overdue. */
  const noOverdue: WorkBoardPage = {
    columns: {
      todo: [task(1, "todo", null), task(2, "todo", null)],
      in_progress: [task(4, "in_progress", null)],
      completed: [],
    },
    next_cursor: null,
  };

  afterEach(() => vi.useRealTimers());

  function renderCard(page: WorkBoardPage, labels: typeof workEn) {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(WED);
    return render(
      <BoardSummary page={page} labels={labels} onOpen={vi.fn()} />,
    );
  }

  it("labels the rows 'Longest overdue' when every listed row is late, else 'Due soonest' (both languages; the label is p.work-compact-group)", () => {
    const mixed: WorkBoardPage = {
      columns: {
        todo: [
          task(2, "todo", "2026-10-20T09:00:00+01:00"),
          task(3, "todo", "2026-11-20T09:00:00+01:00"),
        ],
      },
      next_cursor: null,
    };
    const cases = [
      [workEn, withOverdue, workEn.boardNearestOverdue],
      [workEn, mixed, workEn.boardNearest],
      [workSv, withOverdue, "Äldst försenade"],
      [workSv, mixed, "Närmast i tid"],
    ] as const;
    for (const [labels, page, expected] of cases) {
      const { container, unmount } = renderCard(page, labels);
      const label = container.querySelector("p.work-compact-group");
      expect(label).toHaveTextContent(expected);
      // The label stands right over the rows.
      expect(label?.nextElementSibling).toHaveClass("work-compact-rows");
      unmount();
    }
    expect(workEn.boardNearestOverdue).not.toBe(workEn.boardNearest);
  });

  it("draws no rows label when the card lists no row", () => {
    const { container } = renderCard(noOverdue, workEn);
    expect(container.querySelector(".work-compact-group")).toBeNull();
    expect(container.querySelector(".work-compact-rows-label")).toBeNull();
  });

  it("makes the foot one open button: the label, then what the card leaves out after ' · ', then a chevron", () => {
    const hidden: WorkBoardPage = {
      columns: {
        todo: [
          task(1, "todo", "2026-10-20T09:00:00+01:00"),
          task(2, "todo", null),
          task(3, "todo", null),
        ],
      },
      next_cursor: null,
    };
    const { container } = renderCard(hidden, workEn);
    const open = container.querySelector("button.work-compact-action");
    expect(open).toHaveClass("sk-btn--open");
    expect(open?.querySelector(".work-compact-open-text")).toHaveTextContent(
      "Open Status · 2 more",
    );
    expect(open?.querySelector(".work-compact-more")).toHaveTextContent(
      "· 2 more",
    );
    expect(open?.querySelector("svg")).not.toBeNull();
    expect(container.querySelector(".work-compact-foot")).toBeNull();
  });

  it("heads the card with the kicker Work · Status · the day, and titles it with the overdue count (en)", () => {
    const { container } = renderCard(withOverdue, workEn);
    const kicker = container.querySelector(".work-compact-kind");
    expect(kicker).toHaveTextContent("Work · Status · Wed 4 Nov");
    expect(kicker?.tagName).toBe("H2");
    expect(container.querySelector("h2.work-compact-kind")).toHaveClass(
      "sk-eyebrow",
    );
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      "2 overdue of 4 open",
    );
  });

  it("titles the card with the open count alone when nothing is overdue (en)", () => {
    const { container } = renderCard(noOverdue, workEn);
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      /^3 open$/,
    );
  });

  it("heads the card in Swedish, with the day and the overdue count (sv)", () => {
    const { container } = renderCard(withOverdue, workSv);
    expect(container.querySelector(".work-compact-kind")).toHaveTextContent(
      "Arbete · Status · ons 4 nov",
    );
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      "2 försenade av 4 öppna",
    );
  });

  it("titles the card with the open count alone in Swedish when nothing is overdue (sv)", () => {
    const { container } = renderCard(noOverdue, workSv);
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      /^3 öppna$/,
    );
  });

  it("counts an open Step with the open Tasks: an overdue Step adds to both counts (en)", () => {
    // A Step on the page, overdue and open (the open set is Tasks and Steps): the title reads one more of each.
    const step = {
      ...task(6, "todo", "2026-10-20T09:00:00+01:00", "Steg i uppgift"),
      kind: "step",
      task_id: task(2, "todo", null).id,
    };
    const { container } = renderCard(
      {
        ...withOverdue,
        columns: {
          ...withOverdue.columns,
          todo: [...(withOverdue.columns.todo ?? []), step],
        },
      },
      workEn,
    );
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      "3 overdue of 5 open",
    );
  });

  it("marks the title's counts with + while the page has a next cursor, so they read as lower bounds (en)", () => {
    const { container } = renderCard(
      { ...withOverdue, next_cursor: "019f0000-0000-7000-8000-0000000001e3" },
      workEn,
    );
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      "2+ overdue of 4+ open",
    );
  });

  it("the headline, the bar and the legend count the same open set, Steps included, and say the left-out count (en)", () => {
    // Four open Tasks and one open Step, all in To do: the legend and the bar carry the five open records.
    const step = {
      ...task(6, "todo", null, "Steg i uppgift"),
      kind: "step",
      task_id: task(2, "todo", null).id,
    };
    const { container } = renderCard(
      {
        ...withOverdue,
        columns: {
          ...withOverdue.columns,
          todo: [...(withOverdue.columns.todo ?? []), step],
        },
      },
      workEn,
    );
    expect(container.querySelector("p.work-compact-title")).toHaveTextContent(
      "2 overdue of 5 open",
    );
    const legend = within(
      container.querySelector<HTMLElement>(".sk-counts-bar") as HTMLElement,
    ).getByRole("list");
    expect(
      within(legend)
        .getAllByRole("listitem")
        .map((item) => item.textContent),
    ).toEqual(["To do4", "In progress1", "Blocked0"]);
    const segments = Array.from(
      container.querySelectorAll<HTMLElement>(".sk-counts-bar__segment"),
    );
    expect(segments.map((segment) => segment.style.flexGrow)).toEqual([
      "4",
      "1",
    ]);
    // Two open Tasks have a due date and are listed; the other three open records are said in one line.
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(2);
    expect(screen.getByText("· 3 more")).toHaveClass("work-compact-more");
  });

  it("writes the singular form for one overdue record, in English and Swedish", () => {
    // One overdue Task of three open; the Done Task is not counted.
    const oneOverdue: WorkBoardPage = {
      columns: {
        todo: [
          task(1, "todo", null),
          task(2, "todo", "2026-10-20T09:00:00+01:00"),
        ],
        in_progress: [task(4, "in_progress", null)],
        completed: [task(5, "completed", "2026-10-01T09:00:00+01:00")],
      },
      next_cursor: null,
    };
    const en = renderCard(oneOverdue, workEn);
    expect(
      en.container.querySelector("p.work-compact-title"),
    ).toHaveTextContent(/^1 overdue of 3 open$/);
    en.unmount();
    const sv = renderCard(oneOverdue, workSv);
    expect(
      sv.container.querySelector("p.work-compact-title"),
    ).toHaveTextContent(/^1 försenad av 3 öppna$/);
  });

  it("gives a Task the same meta text on the agenda card (01) and the board card (19)", () => {
    const pending = task(
      6,
      "in_progress",
      "2026-11-04T15:00:00+01:00",
      "Skriv offerten",
    );
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(WED);
    const agenda: WorkAgendaPage = {
      items: [{ ...pending, agenda_group: "today" }],
      next_cursor: null,
    };
    const agendaCard = render(
      <AgendaSummary
        page={agenda}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    const agendaMeta = agendaCard.container.querySelector(
      ".work-compact-row-meta",
    );
    // The time first, then the status: the same order on both cards.
    expect(agendaMeta?.textContent).toBe("today In progress");
    agendaCard.unmount();

    const boardCard = render(
      <BoardSummary
        page={{
          columns: { in_progress: [pending] },
          next_cursor: null,
        }}
        labels={workEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      boardCard.container.querySelector(".work-compact-row-meta")?.textContent,
    ).toBe(agendaMeta?.textContent);
    expect(
      screen.getByRole("button", {
        name: "Skriv offerten, today, In progress",
      }),
    ).toBeInTheDocument();
  });
});
