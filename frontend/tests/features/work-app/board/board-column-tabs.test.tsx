import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { expect, it, vi } from "vitest";
import { boardLabelsEn } from "@/features/work-app/board/board-labels";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkBoardPage } from "@/features/work-app/transport/transport";
import {
  Harness,
  a,
  b,
  c,
  d,
  page,
  search,
  transport,
} from "@tests/helpers/board-phone-fixtures";
import { chooseColumn, columnTab, tabNames } from "./column-tabs";

/*
 * The phone's column tabs (the single layout shows one status at a time). Simulated-host tests (the board with a
 * fake transport), not tests in a real Claude or Android host. The board remembers the last chosen column in module
 * state, so the two tests of the default come first in this file and every later test chooses its column itself.
 */

it("opens on Pågår when something is in progress", () => {
  render(<Harness work={transport()} />);
  expect(columnTab(workEn.taskStatus.in_progress)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(columnTab(workEn.taskStatus.todo)).toHaveAttribute(
    "aria-pressed",
    "false",
  );
  expect(
    screen
      .getAllByRole("region")
      .map((each) => each.getAttribute("aria-label")),
  ).toEqual([workEn.taskStatus.in_progress]);
  expect(screen.getByRole("button", { name: c.title })).toBeInTheDocument();
  expect(screen.queryByRole("button", { name: a.title })).toBeNull();
});

it("the column tabs are the shared Tabs: equal cells in one named group of pressed buttons", () => {
  render(<Harness work={transport()} />);
  const group = screen.getByRole("group", { name: boardLabelsEn.columnTabs });
  expect(group).toHaveClass("sk-tabs", "sk-tabs--equal");
  expect(group.querySelector(".sk-segmented")).toBeNull();
  const tabs = screen.getAllByRole("button", { name: /\s\d+$/ });
  expect(tabs.length).toBeGreaterThan(0);
  tabs.forEach((tab) => {
    expect(tab).toHaveClass("sk-tabs__tab");
    expect(tab).toHaveAttribute("aria-pressed");
  });
  // Exactly one tab of the group is a tab stop (roving focus), as in every Tabs row.
  expect(
    Array.from(group.querySelectorAll("button")).filter(
      (tab) => tab.tabIndex === 0,
    ),
  ).toHaveLength(1);
});

it("opens on the first column when nothing is in progress", () => {
  const idle: WorkBoardPage = {
    ...page,
    columns: { ...page.columns, in_progress: [] },
  };
  render(
    <Harness
      work={transport()}
      initial={{ kind: "board", filters: {}, page: idle }}
    />,
  );
  expect(columnTab(workEn.taskStatus.todo)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: a.title })).toBeInTheDocument();
});

it("the counts of the tabs follow a move while its Ångra lasts", async () => {
  const user = userEvent.setup();
  const moved: WorkBoardPage = {
    ...page,
    columns: {
      ...page.columns,
      todo: [b],
      completed: [d, { ...a, status: "completed", version: 2 }],
    },
  };
  const updateTask = vi
    .fn()
    .mockResolvedValue({ task: { ...a, status: "completed", version: 2 } });
  render(
    <Harness
      work={transport({
        updateTask,
        getWorkBoard: vi.fn().mockResolvedValue(moved),
      })}
    />,
  );
  await chooseColumn(user, workEn.taskStatus.todo);
  expect(tabNames(boardLabelsEn.columnTabs)).toEqual([
    `${workEn.taskStatus.todo} 2`,
    `${workEn.taskStatus.in_progress} 1`,
    `${workEn.taskStatus.blocked} 0`,
    `${workEn.taskStatus.completed} 1`,
    `${workEn.projects} 1`,
  ]);
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: a.title }),
    }),
  );
  await screen.findByRole("button", { name: /^Undo/ });
  // The card stands in To do for its Ångra, but the tabs count where it is now.
  expect(tabNames(boardLabelsEn.columnTabs)).toEqual([
    `${workEn.taskStatus.todo} 1`,
    `${workEn.taskStatus.in_progress} 1`,
    `${workEn.taskStatus.blocked} 0`,
    `${workEn.taskStatus.completed} 2`,
    `${workEn.projects} 1`,
  ]);
  expect(columnTab(workEn.taskStatus.todo)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
});

it("a board that mounts again shows the column chosen last", async () => {
  const user = userEvent.setup();
  const { unmount } = render(<Harness work={transport()} />);
  await chooseColumn(user, workEn.taskStatus.completed);
  expect(screen.getByRole("button", { name: d.title })).toBeInTheDocument();
  unmount();
  render(<Harness work={transport()} />);
  expect(columnTab(workEn.taskStatus.completed)).toHaveAttribute(
    "aria-pressed",
    "true",
  );
  expect(screen.getByRole("button", { name: d.title })).toBeInTheDocument();
});

it("a search shows its hits in every section at once, with no tabs and Klar folded", () => {
  render(search(transport(), "a"));
  expect(
    screen.queryByRole("group", { name: boardLabelsEn.columnTabs }),
  ).toBeNull();
  expect(
    screen
      .getAllByRole("region")
      .map((each) => each.getAttribute("aria-label")),
  ).toEqual([
    workEn.taskStatus.todo,
    workEn.taskStatus.in_progress,
    workEn.taskStatus.completed,
  ]);
  expect(screen.getByRole("button", { name: a.title })).toBeInTheDocument();
  expect(screen.getByRole("button", { name: c.title })).toBeInTheDocument();
});
