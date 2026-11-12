import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  AgendaSummary,
  ContactsSummary,
  HierarchySummary,
} from "@/features/work-app/inline/inline-summary";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { hiddenRows } from "@/features/work-app/shared/work-items";
import {
  type WorkHierarchyFrame,
  type WorkItemRecord,
} from "@/features/work-app/transport/transport";
import {
  agendaItems,
  installFixedClock,
} from "./helpers/inline-summary-fixtures";

installFixedClock();

const hierarchy: WorkHierarchyFrame = {
  kind: "hierarchy",
  nodes: [
    { kind: "domain", id: "d1", parent_id: null, title: "Hem" },
    { kind: "project", id: "p1", parent_id: "d1", title: "Sommarfest" },
    { kind: "project", id: "p2", parent_id: "d1", title: "Renovering" },
  ],
  truncated: false,
};

describe("inline agenda summary", () => {
  it("hiddenRows is the page's rows minus the shown ones and never negative", () => {
    expect(hiddenRows(10, 3)).toBe(7);
    expect(hiddenRows(3, 3)).toBe(0);
    expect(hiddenRows(2, 3)).toBe(0);
  });

  it("puts today's record first, then the overdue records oldest due date first; priority does not reorder them; three rows at most", () => {
    const records: WorkItemRecord[] = [
      {
        kind: "task",
        status: "todo",
        agenda_group: "overdue",
        id: "019f0000-0000-7000-8000-0000000000c1",
        title: "Äldst normal",
        priority: "normal",
        due_at: "2026-10-18T09:00:00Z",
      },
      {
        kind: "task",
        status: "todo",
        agenda_group: "overdue",
        id: "019f0000-0000-7000-8000-0000000000c2",
        title: "Hög nyare",
        priority: "high",
        due_at: "2026-10-22T09:00:00Z",
      },
      {
        kind: "task",
        status: "todo",
        agenda_group: "overdue",
        id: "019f0000-0000-7000-8000-0000000000c3",
        title: "Hög äldst",
        priority: "high",
        due_at: "2026-10-19T09:00:00Z",
      },
      {
        kind: "task",
        status: "in_progress",
        agenda_group: "today",
        id: "019f0000-0000-7000-8000-0000000000c4",
        title: "Idag hög",
        priority: "high",
        due_at: "2026-10-25T10:00:00Z",
      },
    ];
    const { container } = render(
      <AgendaSummary
        page={{ items: records, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 today, 3 overdue")).toBeInTheDocument();
    // Three rows at most: today's record first, then the two oldest overdue records. "Hög nyare", the
    // newest overdue record, is left out; priority does not move it up.
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    expect(titles).toEqual(["Idag hög", "Äldst normal", "Hög äldst"]);
  });

  it("lists today's records higher priority first", () => {
    const records: WorkItemRecord[] = [
      {
        kind: "task",
        status: "todo",
        agenda_group: "today",
        id: "019f0000-0000-7000-8000-0000000000d1",
        title: "Tidig normal",
        priority: "normal",
        due_at: "2026-10-25T08:00:00Z",
      },
      {
        kind: "task",
        status: "todo",
        agenda_group: "today",
        id: "019f0000-0000-7000-8000-0000000000d2",
        title: "Sen hög",
        priority: "high",
        due_at: "2026-10-25T16:00:00Z",
      },
    ];
    const { container } = render(
      <AgendaSummary
        page={{ items: records, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("2 today")).toBeInTheDocument();
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    expect(titles).toEqual(["Sen hög", "Tidig normal"]);
  });

  it("lists a single record due today, with its due word in lower case", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems.slice(2, 3), next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 today")).toBeInTheDocument();
    // The row's meta is the time and the status: the day first, then the in-progress Task's status.
    expect(
      screen.getByRole("button", {
        name: "Skriv offerten, today, In progress",
      }),
    ).toBeInTheDocument();
    expect(screen.getByText("today")).toHaveAttribute("data-tone", "today");
  });

  it("opens the record when a row is pressed, or the agenda when no record opener is given", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const onOpenItem = vi.fn();
    const { unmount } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
        onOpenItem={onOpenItem}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Ring Anna, 4 days overdue" }),
    );
    expect(onOpenItem).toHaveBeenCalledWith(agendaItems[1]);
    expect(onOpen).not.toHaveBeenCalled();
    unmount();
    render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
      />,
    );
    await user.click(
      screen.getByRole("button", { name: "Ring Anna, 4 days overdue" }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("draws no status glyph and writes nothing, even when a write is given", async () => {
    const user = userEvent.setup();
    const onToggle = vi.fn();
    const onOpen = vi.fn();
    const { container } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
        write={{
          work: workEn,
          busy: false,
          onToggle,
          undo: {
            key: "task:x",
            taskId: "019f0000-0000-7000-8000-0000000000a2",
            from: "todo",
            to: "completed",
            version: 2,
            title: "Ring Anna",
          },
          onUndo: vi.fn(),
          onUndoExpire: vi.fn(),
        }}
      />,
    );
    expect(container.querySelector(".work-agenda-glyph")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Mark as done: Ring Anna" }),
    ).toBeNull();
    expect(
      screen.queryByRole("button", { name: workEn.agendaUndo }),
    ).toBeNull();
    await user.click(
      screen.getByRole("button", { name: "Ring Anna, 4 days overdue" }),
    );
    expect(onToggle).not.toHaveBeenCalled();
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("draws no status glyph in Swedish either", () => {
    const { container } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
        write={{
          work: workSv,
          busy: false,
          onToggle: vi.fn(),
          onUndo: vi.fn(),
          onUndoExpire: vi.fn(),
        }}
      />,
    );
    expect(container.querySelector(".work-agenda-glyph")).toBeNull();
    expect(
      screen.queryByRole("button", { name: "Markera klar: Ring Anna" }),
    ).toBeNull();
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
  });
});

describe("inline hierarchy summary", () => {
  it("counts the Projects, and the Tasks when the frame carries them", () => {
    render(
      <HierarchySummary
        frame={{
          ...hierarchy,
          tasks: [
            {
              id: "t1",
              parent_id: "p1",
              title: "Köp tält",
              status: "todo",
              version: 1,
              due_at: null,
              steps: [],
            },
          ],
        }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("region", {
        name: inlineSummaryLabelsEn.kind.hierarchy,
      }),
    ).toBeInTheDocument();
    // The counts are the card's title sentence, "2 projects · 1 task", under the Work eyebrow.
    const title = screen
      .getByRole("region", { name: inlineSummaryLabelsEn.kind.hierarchy })
      .querySelector(".sk-card__title");
    expect(title).toHaveTextContent("2 projects · 1 task");
    expect(title?.previousElementSibling).toHaveTextContent("Work");
  });

  it("leaves the Tasks line out when the frame carries no Tasks, rather than showing zero", () => {
    render(
      <HierarchySummary
        frame={hierarchy}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("2 projekt")).toBeInTheDocument();
    expect(screen.queryByText(/Uppgifter/)).toBeNull();
  });

  it("marks the counts with + when the server cut the tree", () => {
    render(
      <HierarchySummary
        frame={{ ...hierarchy, truncated: true }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("2+ projects")).toBeInTheDocument();
  });

  it("asks for fullscreen from its one Open action", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <HierarchySummary
        frame={hierarchy}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
      />,
    );
    await user.click(
      screen.getByRole("button", {
        name: inlineSummaryLabelsEn.showAll(2, false),
      }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("inline hierarchy summary projects", () => {
  const withTasks: WorkHierarchyFrame = {
    ...hierarchy,
    nodes: [
      ...hierarchy.nodes,
      { kind: "project", id: "p3", parent_id: "d1", title: "Bil" },
      { kind: "project", id: "p4", parent_id: "d1", title: "Båt" },
    ],
    tasks: [
      {
        id: "t1",
        parent_id: "p1",
        title: "Köp tält",
        status: "completed",
        version: 1,
        due_at: null,
        steps: [],
      },
      {
        id: "t2",
        parent_id: "p1",
        title: "Packa",
        status: "todo",
        version: 1,
        due_at: null,
        steps: [],
      },
    ],
  };

  it("names up to three Projects, with progress for those whose Tasks the frame carries", () => {
    render(
      <HierarchySummary
        frame={withTasks}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Sommarfest")).toBeInTheDocument();
    expect(screen.getByText("1 of 2 done")).toBeInTheDocument();
    expect(screen.getByText("Renovering")).toBeInTheDocument();
    expect(screen.getByText("Bil")).toBeInTheDocument();
    expect(screen.queryByText("Båt")).toBeNull();
  });

  it("uses the Swedish progress label for a Swedish host", () => {
    render(
      <HierarchySummary
        frame={withTasks}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 av 2 klara")).toBeInTheDocument();
  });

  it("shows no progress bar when the frame carries no Tasks", () => {
    const { container } = render(
      <HierarchySummary
        frame={hierarchy}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Sommarfest")).toBeInTheDocument();
    expect(container.querySelector(".sk-progress")).toBeNull();
  });
});

describe("inline hierarchy summary ended and open work", () => {
  const mixed: WorkHierarchyFrame = {
    kind: "hierarchy",
    truncated: false,
    nodes: [
      { kind: "domain", id: "d1", parent_id: null, title: "Hem" },
      {
        kind: "project",
        id: "p1",
        parent_id: "d1",
        title: "Gammalt",
        status: "completed",
      },
      {
        kind: "project",
        id: "p2",
        parent_id: "d1",
        title: "Köket",
        status: "active",
      },
      {
        kind: "project",
        id: "p3",
        parent_id: "d1",
        title: "Altanen",
        status: "paused",
      },
      {
        kind: "process",
        id: "q1",
        parent_id: "d1",
        title: "Städning",
        status: "active",
      },
      {
        kind: "process",
        id: "q2",
        parent_id: "d1",
        title: "Gammal rutin",
        status: "archived",
      },
    ],
  };

  function title(labels: typeof inlineSummaryLabelsEn) {
    return screen
      .getByRole("region", { name: labels.kind.hierarchy })
      .querySelector(".sk-card__title");
  }

  it("counts open Projects (active and paused) and open Processes apart, leaving ended ones out", () => {
    render(
      <HierarchySummary
        frame={mixed}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(title(inlineSummaryLabelsEn)).toHaveTextContent(
      "2 projects · 1 process",
    );
    expect(
      screen.getByRole("button", {
        name: inlineSummaryLabelsEn.showAll(3, false),
      }),
    ).toBeInTheDocument();
  });

  it("lists open Projects first, marks a paused one and puts the ended one last with its word", () => {
    render(
      <HierarchySummary
        frame={mixed}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(title(inlineSummaryLabelsSv)).toHaveTextContent(
      "2 projekt · 1 process",
    );
    const rows = Array.from(
      document.querySelectorAll(".work-compact-status"),
    ).map((row) => row.textContent);
    expect(rows).toEqual(["Köket", "Altanen · Pausat", "Gammalt · Avslutat"]);
  });

  it("shows no Process line when there is no open Process", () => {
    render(
      <HierarchySummary
        frame={hierarchy}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(title(inlineSummaryLabelsEn)).toHaveTextContent(/^2 projects$/);
  });

  it("has the same inline label keys in Swedish and English", () => {
    expect(Object.keys(inlineSummaryLabelsSv).sort()).toEqual(
      Object.keys(inlineSummaryLabelsEn).sort(),
    );
  });
});

describe("inline Contact list summary", () => {
  it("counts the matches", () => {
    render(
      <ContactsSummary
        count={3}
        more={false}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("region", { name: inlineSummaryLabelsEn.kind.contacts }),
    ).toBeInTheDocument();
    expect(screen.getByText("3 contacts")).toBeInTheDocument();
    expect(screen.queryByText(/Matches/)).toBeNull();
  });

  it("marks the count with + when more contacts exist, and uses Swedish labels", () => {
    render(
      <ContactsSummary
        count={25}
        more
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("25+ kontakter")).toBeInTheDocument();
  });

  it("says the count as contacts without a search, with the singular for one, and as matches with a search", () => {
    const { unmount } = render(
      <ContactsSummary
        count={1}
        more={false}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 kontakt")).toBeInTheDocument();
    expect(screen.queryByText(/Träffar/)).toBeNull();
    unmount();
    // A whitespace-only query is no search: the count still reads as contacts.
    const { unmount: unmountBlank } = render(
      <ContactsSummary
        count={2}
        more={false}
        query="   "
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("2 kontakter")).toBeInTheDocument();
    unmountBlank();
    render(
      <ContactsSummary
        count={2}
        more={false}
        query="Anna"
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Träffar: 2")).toBeInTheDocument();
    expect(screen.queryByText(/kontakter$/)).toBeNull();
  });

  it("lists the first three names, with an exact match of the search text first", () => {
    const { container } = render(
      <ContactsSummary
        count={4}
        more={false}
        query=" anna "
        contacts={[
          { id: "c1", name: "Annabel Berg" },
          { id: "c2", name: "Bo Berg" },
          { id: "c3", name: "Anna" },
          { id: "c4", name: "Anna Lind" },
        ]}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    expect(titles).toEqual(["Anna", "Annabel Berg", "Bo Berg"]);
    expect(screen.getByText("Matches: 4")).toBeInTheDocument();
    expect(screen.queryByText("Anna Lind")).toBeNull();
  });

  it("keeps the names read order when no name matches the search text exactly", () => {
    const { container } = render(
      <ContactsSummary
        count={2}
        more={false}
        query="Ann"
        contacts={[
          { id: "c1", name: "Bo Berg" },
          { id: "c2", name: "Anna Lind" },
        ]}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    expect(titles).toEqual(["Bo Berg", "Anna Lind"]);
  });
});
