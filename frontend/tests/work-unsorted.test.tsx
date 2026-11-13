import { agendaLabelsSv } from "@/features/work-app/agenda/agenda-labels";
import { boardLabelsSv } from "@/features/work-app/board/board-labels";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi, type Mock } from "vitest";
import { placeChanges } from "@/features/work-app/hierarchy/group-choices";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  taskPlaceLabelsEn,
  taskPlaceLabelsSv,
} from "@/features/work-app/tasks/task-place-labels";
import {
  UnsortedOpenRow,
  UnsortedView,
} from "@/features/work-app/unsorted/unsorted-view";
import type {
  DomainAccent,
  WorkDomain,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { readStylesheet } from "./helpers/stylesheet";

const TASK_A = "019f0000-0000-7000-8000-0000000000c1";
const TASK_B = "019f0000-0000-7000-8000-0000000000c2";
const HOME = "019f0000-0000-7000-8000-0000000000d1";
const WORK = "019f0000-0000-7000-8000-0000000000d2";
const HEALTH = "019f0000-0000-7000-8000-0000000000d3";

const taskA: WorkTask = {
  id: TASK_A,
  title: "Köp ny dammsugare",
  status: "todo",
  due_at: null,
  version: 3,
  domain_id: null,
};
const taskB: WorkTask = {
  id: TASK_B,
  title: "Ring försäkringsbolaget",
  status: "todo",
  due_at: null,
  version: 1,
  domain_id: null,
};
// An unknown accent name (a newer server) is dropped by domainAccentOf, so the button carries no accent.
const domains: WorkDomain[] = [
  { id: HOME, name: "Hem", accent: "teal" },
  { id: WORK, name: "Jobb", accent: "blue" },
  { id: HEALTH, name: "Hälsa", accent: "not-an-accent" as DomainAccent },
];

const RENOVATION = "019f0000-0000-7000-8000-0000000000e1";
const GARDEN = "019f0000-0000-7000-8000-0000000000e2";
// The places the picker offers: one Project and one Process under Hem.
const hierarchy = {
  kind: "hierarchy",
  truncated: false,
  nodes: [
    { kind: "domain", id: HOME, title: "Hem", parent_id: null },
    { kind: "project", id: RENOVATION, title: "Renovering", parent_id: HOME },
    { kind: "process", id: GARDEN, title: "Trädgård", parent_id: HOME },
  ],
};

type Mocks = {
  listUnsortedTasks: Mock;
  listDomains: Mock;
  updateTask: Mock;
  getWorkHierarchy: Mock;
};

/**
 * The transport the sorting view reads through: list_tasks (unsorted) and list_domains, plus
 * update_task, which echoes the Domain it was given and bumps the version.
 */
function makeTransport(
  options: {
    pages?: { items: WorkTask[]; next_cursor: string | null }[];
    domains?: WorkDomain[];
  } = {},
) {
  const pages = [
    ...(options.pages ?? [{ items: [taskA, taskB], next_cursor: null }]),
  ];
  const mock: Mocks = {
    listUnsortedTasks: vi.fn(() =>
      Promise.resolve(pages.shift() ?? { items: [], next_cursor: null }),
    ),
    listDomains: vi.fn(() => Promise.resolve(options.domains ?? domains)),
    updateTask: vi.fn((id: string, version: number, changes: WorkTaskChanges) =>
      Promise.resolve({
        task: {
          id,
          title: "",
          status: "todo",
          due_at: null,
          version: version + 1,
          domain_id: changes.domain_id ?? null,
          project_id: changes.project_id ?? null,
          process_id: changes.process_id ?? null,
        },
      }),
    ),
    getWorkHierarchy: vi.fn(() => Promise.resolve(hierarchy)),
  };
  return { transport: mock as unknown as WorkTransport, mock };
}

function renderView(transport: WorkTransport, locale = workSv) {
  return render(<UnsortedView transport={transport} labels={locale} />);
}

/** The arguments of one update_task call, typed; the mock itself is untyped. */
function updateCall(
  mock: Mocks,
  index: number,
): [string, number, WorkTaskChanges, string] {
  return mock.updateTask.mock.calls[index] as [
    string,
    number,
    WorkTaskChanges,
    string,
  ];
}

/** The Undo button of the sorted row, once its write has settled (the row is disabled while it runs). */
async function undoButton() {
  const button = await screen.findByRole("button", { name: /^Ångra/ });
  await waitFor(() => expect(button).toBeEnabled());
  return button;
}

/** The Domain buttons of the row with this title. */
function domainButtons(title: string) {
  return within(
    screen.getByRole("group", { name: workSv.unsortedRowFor(title) }),
  ).getAllByRole("button");
}

describe("UnsortedView (Att sortera)", () => {
  it("reads the unsorted Tasks and the Domains when it opens", async () => {
    const { transport, mock } = makeTransport();
    renderView(transport);

    expect(await screen.findByText("Köp ny dammsugare")).toBeInTheDocument();
    expect(screen.getByText("Ring försäkringsbolaget")).toBeInTheDocument();
    expect(mock.listUnsortedTasks).toHaveBeenCalledTimes(1);
    expect(mock.listDomains).toHaveBeenCalledTimes(1);
  });

  it("shows one button per Domain in each row, with the Domain accent where the server gives one", async () => {
    const { transport } = makeTransport();
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    const buttons = domainButtons("Köp ny dammsugare");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Hem",
      "Jobb",
      "Hälsa",
    ]);
    expect(buttons[0]).toHaveAttribute("data-accent", "teal");
    expect(buttons[1]).toHaveAttribute("data-accent", "blue");
    expect(buttons[2]).not.toHaveAttribute("data-accent");
  });

  it("sorts a Task into the Domain it taps, against its version, and the row stays in its place with Undo when the reply comes", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[1]!);

    expect(mock.updateTask).toHaveBeenCalledTimes(1);
    const [id, version, changes, key] = updateCall(mock, 0);
    expect(id).toBe(TASK_A);
    expect(version).toBe(3);
    expect(changes).toEqual(placeChanges({ kind: "domain", id: WORK }));
    expect(typeof key).toBe("string");
    await undoButton();
    // The sorted row keeps its title and its place; its Domain buttons are replaced by its own Undo line.
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();
    expect(
      screen.queryByRole("group", {
        name: workSv.unsortedRowFor("Köp ny dammsugare"),
      }),
    ).not.toBeInTheDocument();
    expect(screen.getByText("Ring försäkringsbolaget")).toBeInTheDocument();
    // The Undo line of the row names the Domain the Task went into, as its status line.
    const line = screen.getByRole("status");
    expect(line.parentElement).toHaveClass("work-agenda-undo");
    expect(line).toHaveTextContent("Flyttad till Jobb");
  });

  it("Ångra clears the Domain again against the version the sort left, and puts the row back in its place", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[0]!);
    await user.click(await undoButton());

    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: /^Ångra/ }),
      ).not.toBeInTheDocument(),
    );
    expect(mock.updateTask).toHaveBeenCalledTimes(2);
    const [id, version, changes, undoKey] = updateCall(mock, 1);
    expect(id).toBe(TASK_A);
    // The undo is written against the version the sort left (3 + 1), with domain_id cleared.
    expect(version).toBe(4);
    expect(changes).toEqual(placeChanges(null));
    expect(undoKey).not.toBe(updateCall(mock, 0)[3]);
    // The row is back above the other Task.
    const titles = screen
      .getAllByRole("listitem")
      .map((item) => item.textContent);
    expect(titles[0]).toContain("Köp ny dammsugare");
    expect(titles[1]).toContain("Ring försäkringsbolaget");
  });

  it("two quick taps on different rows give two writes while the first is still unanswered", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    const replies: (() => void)[] = [];
    mock.updateTask.mockImplementation(
      (id: string, version: number, changes: WorkTaskChanges) =>
        new Promise((resolve) => {
          replies.push(() =>
            resolve({
              task: {
                id,
                title: "",
                status: "todo",
                due_at: null,
                version: version + 1,
                domain_id: changes.domain_id ?? null,
              },
            }),
          );
        }),
    );
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[0]!);
    // The written row is shut and marked busy; the other row is still pressable and nothing moved.
    const rowA = screen.getByText("Köp ny dammsugare").closest("li")!;
    expect(rowA).toHaveAttribute("aria-busy", "true");
    domainButtons("Köp ny dammsugare").forEach((button) =>
      expect(button).toBeDisabled(),
    );
    domainButtons("Ring försäkringsbolaget").forEach((button) =>
      expect(button).toBeEnabled(),
    );
    // The first sort has no Undo line yet, so no "Moving…" line either.
    expect(screen.queryByText(agendaLabelsSv.moving)).not.toBeInTheDocument();

    await user.click(domainButtons("Ring försäkringsbolaget")[1]!);

    expect(mock.updateTask).toHaveBeenCalledTimes(2);
    expect(updateCall(mock, 0)[0]).toBe(TASK_A);
    expect(updateCall(mock, 1)[0]).toBe(TASK_B);
    expect(updateCall(mock, 1)[2]).toEqual(
      placeChanges({ kind: "domain", id: WORK }),
    );
    expect(updateCall(mock, 1)[3]).not.toBe(updateCall(mock, 0)[3]);
    // No optimistic removal: both rows stay until their replies come.
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();
    expect(screen.getByText("Ring försäkringsbolaget")).toBeInTheDocument();

    // The first reply lands while the second write is open: the sorted row keeps its place and says "Moving…"
    // in its status line with no Undo button, until the second reply lands too.
    replies[0]!();
    await waitFor(() =>
      expect(screen.getByText(agendaLabelsSv.moving)).toBeInTheDocument(),
    );
    expect(screen.getByText(agendaLabelsSv.moving).parentElement).toHaveClass(
      "work-agenda-undo",
    );
    expect(screen.getByText(agendaLabelsSv.moving).closest("li")).toHaveClass(
      "work-unsorted-row",
    );
    expect(
      screen.queryByRole("button", { name: /^Ångra/ }),
    ).not.toBeInTheDocument();

    replies[1]!();
    // The Undo line shows the last sort that landed, for its own row; Undo works once nothing else is written.
    await undoButton();
    expect(screen.getByText("Ring försäkringsbolaget")).toBeInTheDocument();
    expect(screen.queryByText("Köp ny dammsugare")).not.toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent("Flyttad till Jobb");
  });

  it("a second tap on the row being written is dropped, and a failed row can be tried again beside a busy one", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    mock.updateTask.mockRejectedValueOnce(new Error("network"));
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[0]!);
    expect(
      await screen.findByText(boardLabelsSv.moveFailed),
    ).toBeInTheDocument();
    // Tap the failed row again: the same signature reuses the key.
    await user.click(domainButtons("Köp ny dammsugare")[0]!);
    await undoButton();
    expect(mock.updateTask).toHaveBeenCalledTimes(2);
    expect(updateCall(mock, 1)[3]).toBe(updateCall(mock, 0)[3]);
  });

  it("a failed write keeps the row and Try again repeats it with the same key", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    mock.updateTask.mockRejectedValueOnce(new Error("network"));
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[1]!);

    expect(
      await screen.findByText(boardLabelsSv.moveFailed),
    ).toBeInTheDocument();
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: workSv.retry }));

    await undoButton();
    expect(mock.updateTask).toHaveBeenCalledTimes(2);
    expect(updateCall(mock, 1)[3]).toBe(updateCall(mock, 0)[3]);
  });

  it("a conflict keeps the row and shows the conflict notice with a reload", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport();
    mock.updateTask.mockRejectedValueOnce(
      Object.assign(new Error("conflict"), { code: "conflict" }),
    );
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(domainButtons("Köp ny dammsugare")[0]!);

    expect(await screen.findByRole("alert")).toHaveTextContent(
      boardLabelsSv.conflict,
    );
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();
    expect(mock.listUnsortedTasks).toHaveBeenCalledTimes(1);
  });

  it("shows the empty state when no Task is unsorted", async () => {
    const { transport } = makeTransport({
      pages: [{ items: [], next_cursor: null }],
    });
    renderView(transport);

    expect(await screen.findByText(workSv.unsortedEmpty)).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("shows a notice and no Domain buttons when there is no Domain to sort into", async () => {
    const { transport } = makeTransport({ domains: [] });
    renderView(transport);

    expect(
      await screen.findByText(workSv.unsortedNoDomains),
    ).toBeInTheDocument();
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();
    expect(screen.queryByRole("group")).not.toBeInTheDocument();
  });

  it("loads the next page of unsorted Tasks with its cursor and appends it", async () => {
    const user = userEvent.setup();
    const { transport, mock } = makeTransport({
      pages: [
        { items: [taskA], next_cursor: "cursor-2" },
        { items: [taskB], next_cursor: null },
      ],
    });
    renderView(transport);
    await screen.findByText("Köp ny dammsugare");

    await user.click(screen.getByRole("button", { name: workSv.more }));

    expect(
      await screen.findByText("Ring försäkringsbolaget"),
    ).toBeInTheDocument();
    expect(mock.listUnsortedTasks).toHaveBeenLastCalledWith("cursor-2");
    expect(screen.getByText("Köp ny dammsugare")).toBeInTheDocument();
  });

  it("has English labels for the same view", async () => {
    const { transport } = makeTransport();
    renderView(transport, workEn);

    expect(
      await screen.findByText(taskPlaceLabelsEn.unsortedIntro),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", {
        name: workEn.unsortedRowFor("Köp ny dammsugare"),
      }),
    ).toBeInTheDocument();
  });
});

describe("UnsortedOpenRow (the quiet row after the agenda)", () => {
  it("shows the count in Swedish and opens the view when pressed", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <UnsortedOpenRow
        count={3}
        more={false}
        labels={workSv}
        onOpen={onOpen}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Att sortera (3)" }));

    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("shows a full first page as N+ in English", () => {
    render(
      <UnsortedOpenRow
        count={100}
        more={true}
        labels={workEn}
        onOpen={vi.fn()}
      />,
    );

    expect(
      screen.getByRole("button", { name: "Unsorted (100+)" }),
    ).toBeInTheDocument();
  });

  it("has a press area of at least 44 px high and wide", () => {
    // jsdom applies no CSS. The row is full width (unsorted.css); its 44 px height is the family's button
    // rule (family.css), not a rule of its own, so unsorted.css sets no min-height.
    const rule = readStylesheet("features/work-app/unsorted/unsorted.css").rule(
      ".sidekick-work .work-unsorted-open",
    );
    expect(rule.width).toBe("100%");
    expect(rule).not.toHaveProperty(["min-height"]);
    const family = readStylesheet("features/mcp-apps/ui/family.css").rule(
      ":is(.sidekick-work, .sidekick-journal, .sidekick-shopping, .sidekick-control) button, .sk-btn",
    );
    expect(family["min-height"]).toBe("var(--sk-tap)");
    // The tap token is 44 px in Claude; the phone raises it to 48 px (mobile.css).
    expect(
      readStylesheet("features/mcp-apps/ui/tokens.css").rule(":root")[
        "--sk-tap"
      ],
    ).toBe("2.75rem");
  });
  describe("the place picker (Välj plats…)", () => {
    it("reads the places only when a picker is opened, and sorts the Task into the chosen Project", async () => {
      const user = userEvent.setup();
      const { transport, mock } = makeTransport();
      renderView(transport);
      await screen.findByText("Köp ny dammsugare");
      expect(mock.getWorkHierarchy).not.toHaveBeenCalled();

      const pick = screen.getAllByRole("button", {
        name: taskPlaceLabelsSv.choosePlace,
      })[0]!;
      expect(pick).toHaveAttribute("aria-expanded", "false");
      await user.click(pick);
      expect(pick).toHaveAttribute("aria-expanded", "true");
      const select = await screen.findByRole("combobox", {
        name: taskPlaceLabelsSv.pickerFor("Köp ny dammsugare"),
      });
      expect(mock.getWorkHierarchy).toHaveBeenCalledTimes(1);

      await user.selectOptions(select, "Renovering");

      await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(1));
      const [id, version, changes] = updateCall(mock, 0);
      expect(id).toBe(TASK_A);
      expect(version).toBe(3);
      expect(changes).toEqual(
        placeChanges({ kind: "project", id: RENOVATION }),
      );
      await undoButton();
      expect(screen.getByRole("status")).toHaveTextContent(
        "Flyttad till Renovering",
      );
      // The row left the list but keeps its Undo line; the other row is still sortable.
      expect(
        screen.queryByRole("combobox", { name: /Plats för/ }),
      ).not.toBeInTheDocument();
    });

    it("sorts into a Process and Ångra writes the place back to none", async () => {
      const user = userEvent.setup();
      const { transport, mock } = makeTransport();
      renderView(transport);
      await screen.findByText("Köp ny dammsugare");

      await user.click(
        screen.getAllByRole("button", {
          name: taskPlaceLabelsSv.choosePlace,
        })[0]!,
      );
      await user.selectOptions(
        await screen.findByRole("combobox"),
        "Trädgård (process)",
      );
      await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(1));
      expect(updateCall(mock, 0)[2]).toEqual(
        placeChanges({ kind: "process", id: GARDEN }),
      );

      await user.click(await undoButton());
      await waitFor(() => expect(mock.updateTask).toHaveBeenCalledTimes(2));
      expect(updateCall(mock, 1)[1]).toBe(4);
      expect(updateCall(mock, 1)[2]).toEqual(placeChanges(null));
    });

    it("offers the picker only where the host can write the place", async () => {
      const { transport } = makeTransport();
      Object.assign(transport, {
        supportsTool: () => true,
        supportsCall: () => false,
      });
      renderView(transport);
      await screen.findByText("Köp ny dammsugare");

      expect(
        screen.queryByRole("button", { name: taskPlaceLabelsSv.choosePlace }),
      ).not.toBeInTheDocument();
      // The Domain buttons stay.
      expect(domainButtons("Köp ny dammsugare")).toHaveLength(3);
    });
  });
});
