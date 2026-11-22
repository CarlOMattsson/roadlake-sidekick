import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";

import {
  controlEn,
  controlSv,
  type ControlLabels,
} from "@/features/control-app/labels";
import { HistoryView } from "@/features/control-app/history-view";
import { TrashView } from "@/features/control-app/trash-view";
import type {
  ActivityRecord,
  ChangeRecord,
  ControlTransport,
  TrashItem,
} from "@/features/control-app/transport";
import type { RoomTarget } from "@/features/mcp-apps/room-types";

// Friday 20 November 2026.
const now = () => new Date("2026-11-20T11:00:00Z");

/** The frame's width as the browser would measure it; jsdom has no layout, so the tests say how wide it is. */
function frameIsPx(width: number) {
  vi.spyOn(HTMLElement.prototype, "getBoundingClientRect").mockReturnValue({
    width,
    height: 600,
    x: 0,
    y: 0,
    top: 0,
    left: 0,
    right: width,
    bottom: 600,
    toJSON: () => ({}),
  });
}

afterEach(() => vi.restoreAllMocks());

const task: ChangeRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000003b1",
  title: "Ring Anna",
  version: 3,
  action: "updated",
  state: "active",
  actor: "you",
  occurred_at: "2026-11-20T08:05:00Z",
};
const bought: ChangeRecord = {
  kind: "shopping_item",
  id: "019f0000-0000-7000-8000-0000000003a1",
  title: "Mjölk",
  version: 2,
  action: "purchased",
  state: "active",
  actor: "claude",
  occurred_at: "2026-11-19T13:30:00Z",
  undo_tool: "set_shopping_item_purchased",
};
const trashedTask: ChangeRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000003c1",
  title: "Förbered pitchen",
  version: 4,
  action: "trashed",
  state: "trashed",
  actor: "you",
  occurred_at: "2026-11-17T12:00:00Z",
};
const taskRun: ActivityRecord = {
  id: "019f0000-0000-7000-8000-000000000201",
  category: "task_maintenance",
  source: "assistant",
  operation: "reorder_board_column",
  state: "applied",
  aggregate_type: "task",
  aggregate_id: "019f0000-0000-7000-8000-0000000003d1",
  summary: "Flyttade Förbered pitchen till Klar",
  occurred_at: "2026-11-20T09:55:00Z",
};
const aiRun: ActivityRecord = {
  ...taskRun,
  id: "019f0000-0000-7000-8000-000000000202",
  category: "ai_steps",
  aggregate_type: "ai_step_run",
  aggregate_id: "019f0000-0000-7000-8000-0000000003e1",
  summary: "Körde ett steg",
  occurred_at: "2026-11-20T09:50:00Z",
};

function makeTransport() {
  return {
    trash: vi.fn(() =>
      Promise.resolve({ items: [], has_more: false, next_cursor: null }),
    ),
    restore: vi.fn(() => Promise.resolve({})),
    changes: vi.fn(() => Promise.resolve({ changes: [] })),
    undoPurchase: vi.fn(() => Promise.resolve({})),
    memoryStatus: vi.fn(),
    setMemory: vi.fn(),
    activity: vi.fn(),
  } satisfies ControlTransport;
}

function renderHistory(
  options: {
    labels?: ControlLabels;
    onOpen?: (target: RoomTarget) => void;
    changes?: ChangeRecord[];
    activity?: ActivityRecord[];
  } = {},
) {
  return render(
    <HistoryView
      changes={{ changes: options.changes ?? [task, bought, trashedTask] }}
      activity={{ items: options.activity ?? [], next_cursor: null }}
      transport={makeTransport()}
      labels={options.labels ?? controlSv}
      now={now}
      onOpen={options.onOpen}
      full
    />,
  );
}

const rowOf = (text: string) =>
  screen.getByText(text).closest<HTMLElement>('[role="row"]')!;

describe("History in the full view under 48rem", () => {
  it("groups the rows by day under a heading, each day its own list, and is no table", () => {
    frameIsPx(600);
    renderHistory();

    expect(screen.queryByRole("table")).toBeNull();
    expect(
      screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent),
    ).toEqual(["Idag", "Igår", "tis 17 nov"]);
    const today = screen.getByRole("list", { name: "Historik · Idag" });
    expect(within(today).getByText("Ring Anna")).toBeInTheDocument();
    expect(within(today).queryByText("Mjölk")).toBeNull();
    // The row itself is what it was: a meta line with kind, event, who and when, and no open button.
    expect(screen.queryByRole("button", { name: /Ring Anna/ })).toBeNull();
  });

  it("names the days in English", () => {
    frameIsPx(600);
    renderHistory({ labels: controlEn });

    expect(
      screen.getAllByRole("heading", { level: 3 }).map((h) => h.textContent),
    ).toEqual(["Today", "Yesterday", "Tue 17 Nov"]);
  });
});

describe("History in the full view from 48rem", () => {
  it("is a table with the columns What, Room, Event, Who and When, and a heading row for each day", () => {
    frameIsPx(800);
    renderHistory();

    const table = screen.getByRole("table", { name: "Historik" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((head) => head.textContent),
    ).toEqual(["Vad", "Rum", "Händelse", "Vem", "När", "Åtgärd"]);
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((head) => head.textContent),
    ).toEqual(["Idag", "Igår", "tis 17 nov"]);
    const cells = within(rowOf("Ring Anna"))
      .getAllByRole("cell")
      .map((cell) => cell.textContent);
    expect(cells.slice(1, 5)).toEqual(["Arbete", "ändrad", "Du", "idag 09:05"]);
    expect(
      within(rowOf("Mjölk"))
        .getAllByRole("cell")
        .map((cell) => cell.textContent)
        .slice(1, 5),
    ).toEqual(["Inköp", "köpt", "Claude", "igår 14:30"]);
  });

  it("is the same table in English", () => {
    frameIsPx(800);
    renderHistory({ labels: controlEn });

    const table = screen.getByRole("table", { name: "History" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((head) => head.textContent),
    ).toEqual(["What", "Room", "Event", "Who", "When", "Action"]);
    expect(
      within(table)
        .getAllByRole("rowheader")
        .map((head) => head.textContent),
    ).toEqual(["Today", "Yesterday", "Tue 17 Nov"]);
  });

  it("opens the record of a row that has a page, with hover, a data-sk-row and a ›", async () => {
    frameIsPx(800);
    const user = userEvent.setup();
    const onOpen = vi.fn();
    renderHistory({ onOpen });

    const row = rowOf("Ring Anna");
    expect(row).toHaveAttribute("data-sk-row");
    expect(row.querySelector(".control-tchev svg")).not.toBeNull();
    const open = within(row).getByRole("button", { name: /Ring Anna/ });
    await user.click(open);
    expect(onOpen).toHaveBeenCalledWith({
      room: "work",
      view: "task",
      id: task.id,
      label: "Ring Anna",
    });
  });

  it("opens by keyboard", async () => {
    frameIsPx(800);
    const user = userEvent.setup();
    const onOpen = vi.fn();
    renderHistory({ onOpen });

    await user.tab();
    expect(screen.getByRole("button", { name: /Ring Anna/ })).toHaveFocus();
    await user.keyboard("{Enter}");
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("gives a row with no page to open no hover, no button over the row and no ›", () => {
    frameIsPx(800);
    const onOpen = vi.fn();
    renderHistory({ onOpen });

    // A shopping item has no page; its only button is Undo.
    const bought = rowOf("Mjölk");
    expect(bought).not.toHaveAttribute("data-sk-row");
    expect(bought.querySelector(".control-topen")).toBeNull();
    expect(bought.querySelector(".control-tchev svg")).toBeNull();
    expect(
      within(bought)
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["Ångra Mjölk"]);
    // A record in the trash has none either; Restore is its way back.
    const gone = rowOf("Förbered pitchen");
    expect(gone).not.toHaveAttribute("data-sk-row");
    expect(
      within(gone)
        .getAllByRole("button")
        .map((button) => button.getAttribute("aria-label")),
    ).toEqual(["Återställ Förbered pitchen"]);
  });

  it("opens the task an activity entry names, and not the run of an AI step", async () => {
    frameIsPx(800);
    const user = userEvent.setup();
    const onOpen = vi.fn();
    renderHistory({ onOpen, changes: [], activity: [taskRun, aiRun] });

    expect(rowOf("Körde ett steg")).not.toHaveAttribute("data-sk-row");
    await user.click(
      within(rowOf("Flyttade Förbered pitchen till Klar")).getByRole("button"),
    );
    expect(onOpen).toHaveBeenCalledWith({
      room: "work",
      view: "task",
      id: taskRun.aggregate_id,
      label: undefined,
    });
  });

  it("has no row that opens where the host cannot open a record", () => {
    frameIsPx(800);
    renderHistory();

    expect(document.querySelector("[data-sk-row]")).toBeNull();
    expect(screen.queryByRole("button", { name: /Ring Anna/ })).toBeNull();
  });

  it("keeps Undo working in the table", async () => {
    frameIsPx(800);
    const user = userEvent.setup();
    const transport = makeTransport();
    render(
      <HistoryView
        changes={{ changes: [bought] }}
        transport={transport}
        labels={controlSv}
        now={now}
        full
      />,
    );

    await user.click(screen.getByRole("button", { name: "Ångra Mjölk" }));
    expect(transport.undoPurchase).toHaveBeenCalledTimes(1);
  });
});

describe("Trash in the full view from 48rem", () => {
  const item: TrashItem = {
    kind: "task",
    id: "019f0000-0000-7000-8000-000000000101",
    label: "Förbered pitchen",
    trashed_at: "2026-11-19T13:30:00Z",
    version: 4,
  };

  it("is a table with What, Room, Deleted and a Restore at the end, and no row opens", async () => {
    frameIsPx(800);
    const user = userEvent.setup();
    const transport = makeTransport();
    render(
      <TrashView
        initial={{ items: [item], has_more: false, next_cursor: null }}
        transport={transport}
        labels={controlSv}
        now={now}
        onOpen={vi.fn()}
        full
      />,
    );

    const table = screen.getByRole("table", { name: "Borttaget" });
    expect(
      within(table)
        .getAllByRole("columnheader")
        .map((head) => head.textContent),
    ).toEqual(["Vad", "Rum", "Borttaget", "Åtgärd"]);
    const row = rowOf("Förbered pitchen");
    expect(
      within(row)
        .getAllByRole("cell")
        .map((cell) => cell.textContent)
        .slice(1, 3),
    ).toEqual(["Arbete", "igår 14:30"]);
    expect(row).not.toHaveAttribute("data-sk-row");
    await user.click(
      within(row).getByRole("button", { name: "Återställ Förbered pitchen" }),
    );
    expect(transport.restore).toHaveBeenCalledTimes(1);
  });

  it("is rows again under 48rem", () => {
    frameIsPx(600);
    render(
      <TrashView
        initial={{ items: [item], has_more: false, next_cursor: null }}
        transport={makeTransport()}
        labels={controlSv}
        now={now}
        full
      />,
    );

    expect(screen.queryByRole("table")).toBeNull();
    expect(screen.getByRole("list", { name: "Borttaget" })).toBeVisible();
  });
});
