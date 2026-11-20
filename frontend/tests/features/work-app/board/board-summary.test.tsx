import { boardLabelsEn } from "@/features/work-app/board/board-labels";
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
const openBoardName = new RegExp(`^${boardLabelsEn.openBoard}`);

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
  // The page has a next cursor, so the count is a floor: "3+ more", in the card's one main link.
  expect(screen.getByText("· 3+ more")).toHaveClass("sk-open-link__more");
  expect(screen.queryByText(boardLabelsEn.more)).toBeNull();
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
  // one "2 more" in the open link instead of one line per status.
  expect(screen.getByText("· 2 more")).toHaveClass("sk-open-link__more");
  expect(
    screen.queryByText(/^\+\d+ (To do|Blocked|Done|In progress)$/),
  ).toBeNull();
  expect(container.querySelectorAll(".sk-open-link__more")).toHaveLength(1);
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
  const { container } = render(
    <WorkView
      transport={workWithBoard()}
      initial={listedAll}
      labels={workEn}
      fullscreen={vi.fn()}
    />,
  );
  // Nothing is hidden, so the link counts nothing; the title's "+" says the counts are a floor, and no line says
  // "more exist" twice.
  expect(container.querySelectorAll(".sk-open-link__more")).toHaveLength(0);
  expect(screen.queryByText(boardLabelsEn.more)).toBeNull();
  expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
    "2+ open",
  );
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
  expect(container.querySelectorAll(".sk-open-link__more")).toHaveLength(0);
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
      [workEn, withOverdue, boardLabelsEn.nearestOverdue],
      [workEn, mixed, boardLabelsEn.nearest],
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
    expect(boardLabelsEn.nearestOverdue).not.toBe(boardLabelsEn.nearest);
  });

  it("draws no rows label when the card lists no row", () => {
    const { container } = renderCard(noOverdue, workEn);
    expect(container.querySelector(".work-compact-group")).toBeNull();
    expect(container.querySelector(".work-compact-rows-label")).toBeNull();
  });

  it("ends in one OpenLink: the label, then what the card leaves out after ' · ', then a chevron", () => {
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
    const open = container.querySelector("button.sk-open-link");
    expect(open).toHaveClass("sk-btn--open");
    expect(open?.querySelector(".sk-open-link__text")).toHaveTextContent(
      "Open Status · 2 more",
    );
    expect(open?.querySelector(".sk-open-link__more")).toHaveTextContent(
      "· 2 more",
    );
    expect(open?.querySelector("svg")).not.toBeNull();
    // Last in the card.
    expect(container.querySelector(".sk-card")?.lastElementChild).toBe(open);
  });

  it("heads the card with the kicker Work · Status · the day, and titles it with the overdue count (en)", () => {
    const { container } = renderCard(withOverdue, workEn);
    const kicker = container.querySelector(".sk-eyebrow");
    expect(kicker).toHaveTextContent("Work · Status · Wed 4 Nov");
    // The kicker is the card's eyebrow (a paragraph); the title is the card's heading.
    expect(kicker?.tagName).toBe("P");
    expect(kicker).toHaveClass("sk-eyebrow");
    expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
      "2 overdue of 4 open",
    );
  });

  it("titles the card with the open count alone when nothing is overdue (en)", () => {
    const { container } = renderCard(noOverdue, workEn);
    expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
      /^3 open$/,
    );
  });

  it("heads the card in Swedish, with the day and the overdue count (sv)", () => {
    const { container } = renderCard(withOverdue, workSv);
    expect(container.querySelector(".sk-eyebrow")).toHaveTextContent(
      "Arbete · Status · ons 4 nov",
    );
    expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
      "2 försenade av 4 öppna",
    );
  });

  it("titles the card with the open count alone in Swedish when nothing is overdue (sv)", () => {
    const { container } = renderCard(noOverdue, workSv);
    expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
      /^3 öppna$/,
    );
  });

  it("marks the title's counts with + while the page has a next cursor, so they read as lower bounds (en)", () => {
    const { container } = renderCard(
      { ...withOverdue, next_cursor: "019f0000-0000-7000-8000-0000000001e3" },
      workEn,
    );
    expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
      "2+ overdue of 4+ open",
    );
  });

  describe("with the server's totals, the card and the text to the model count the whole board", () => {
    // A page of three Tasks of a board with 38 open Tasks, 7 of them overdue (the page is only the first part).
    const bigBoard: WorkBoardPage = {
      columns: {
        todo: [
          task(2, "todo", "2026-10-20T09:00:00+01:00"),
          task(3, "todo", "2026-10-21T09:00:00+01:00"),
          task(1, "todo", "2026-12-01T09:00:00+01:00"),
        ],
      },
      next_cursor: "019f0000-0000-7000-8000-0000000001e9",
      column_totals: { todo: 35, in_progress: 2, blocked: 1, completed: 9 },
      overdue_total: 7,
    };

    function renderWithContext(labels: typeof workEn) {
      const onModelContext = vi.fn();
      vi.useFakeTimers({ toFake: ["Date"] });
      vi.setSystemTime(WED);
      const view = render(
        <BoardSummary
          page={bigBoard}
          labels={labels}
          onOpen={vi.fn()}
          onModelContext={onModelContext}
        />,
      );
      return { ...view, onModelContext };
    }

    it("titles the card and fills the bar from the totals, with no + (en)", () => {
      const { container } = renderWithContext(workEn);
      expect(container.querySelector("h2.sk-card__title")).toHaveTextContent(
        /^7 overdue of 38 open$/,
      );
      const legend = within(
        container.querySelector<HTMLElement>(".sk-counts-bar") as HTMLElement,
      ).getByRole("list");
      expect(
        within(legend)
          .getAllByRole("listitem")
          .map((item) => item.textContent),
      ).toEqual(["To do35", "In progress2", "Blocked1"]);
      // 38 open, the three listed rows leave 35 for the foot; nothing says "more not shown".
      expect(screen.getByText("· 35 more")).toHaveClass("sk-open-link__more");
      expect(screen.queryByText(boardLabelsEn.more)).toBeNull();
    });

    it("sends the model the same numbers as the card, without titles (sv and en)", () => {
      const sv = renderWithContext(workSv);
      expect(sv.onModelContext).toHaveBeenCalledWith(
        "Status: 35 att göra, 2 pågår, 1 blockerad, 9 klar; 7 försenade",
      );
      expect(sv.container.querySelector("h2.sk-card__title")).toHaveTextContent(
        "7 försenade av 38 öppna",
      );
      sv.unmount();
      const en = renderWithContext(workEn);
      expect(en.onModelContext).toHaveBeenCalledWith(
        "Status: 35 to do, 2 in progress, 1 blocked, 9 done; 7 overdue",
      );
    });
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
    expect(en.container.querySelector("h2.sk-card__title")).toHaveTextContent(
      /^1 overdue of 3 open$/,
    );
    en.unmount();
    const sv = renderCard(oneOverdue, workSv);
    expect(sv.container.querySelector("h2.sk-card__title")).toHaveTextContent(
      /^1 försenad av 3 öppna$/,
    );
  });

  it("gives a Task the time and the status in that order on the board card (19), and the agenda card (01) drops the day its Idag group names", () => {
    const pending = task(
      6,
      "in_progress",
      "2026-11-04T23:59:00+01:00",
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
    // Under the group Today the day is not repeated: the agenda's meta is the status only.
    expect(agendaMeta?.textContent).toBe("In progress");
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
    // The board has no group, so the time stands first, then the status.
    expect(
      boardCard.container.querySelector(".work-compact-row-meta")?.textContent,
    ).toBe("Today In progress");
    expect(
      screen.getByRole("button", {
        name: "Skriv offerten, Today, In progress",
      }),
    ).toBeInTheDocument();
  });
});

it("opens the pressed Task itself, not just the board, and Back returns to the card", async () => {
  const user = userEvent.setup();
  const fullscreen = vi.fn();
  const openRecord = vi.fn();
  const work = {
    getWorkBoard: vi.fn().mockResolvedValue({ columns: {}, next_cursor: null }),
    getTask: vi.fn().mockResolvedValue({ task: { ...dueSoon, version: 1 } }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as WorkTransport;
  render(
    <WorkView
      transport={work}
      initial={dueFrame}
      labels={workEn}
      fullscreen={fullscreen}
      openRecord={openRecord}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: new RegExp(`^${dueSoon.title}`) }),
  );
  // The room is told which record to show in the full view; the bare fullscreen request is not what a row sends.
  expect(openRecord).toHaveBeenCalledWith({
    room: "work",
    view: "task",
    id: dueSoon.id,
    label: dueSoon.title,
    from: "board",
  });
  expect(fullscreen).not.toHaveBeenCalled();
  expect(work.getTask).toHaveBeenCalledWith(dueSoon.id);
  // Back returns to the board card, as it does from the agenda card.
  await user.click(
    await screen.findByRole("button", { name: new RegExp(workEn.board) }),
  );
  expect(screen.getByRole("button", { name: openBoardName })).toBeVisible();
});

it("a row opens the board when no record opener is given, and the foot always opens the board", async () => {
  const user = userEvent.setup();
  const onOpen = vi.fn();
  const onOpenItem = vi.fn();
  render(
    <BoardSummary
      page={dueFrame.page}
      labels={workEn}
      onOpen={onOpen}
      onOpenItem={onOpenItem}
    />,
  );
  await user.click(
    screen.getByRole("button", { name: new RegExp(`^${dueMid.title}`) }),
  );
  expect(onOpenItem).toHaveBeenCalledWith(dueMid);
  expect(onOpen).not.toHaveBeenCalled();
  await user.click(screen.getByRole("button", { name: openBoardName }));
  expect(onOpen).toHaveBeenCalledTimes(1);
  expect(onOpenItem).toHaveBeenCalledTimes(1);
});
