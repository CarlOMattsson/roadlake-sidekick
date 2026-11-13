import {
  act,
  fireEvent,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda/agenda-undo";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type {
  WorkItemRecord,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  OTHER_ID,
  overdue,
  todayTask,
  makeTransport,
  renderAgenda,
  rowOf,
  openMenu,
  openRow,
  undoLineOf,
} from "./helpers/agenda-triage-fixtures";

afterEach(() => {
  // A right click marks the row menu as used, and the tip under the list leaves with it.
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

it("a row done from Försenade stands on its place for its Undo: the count waits, the line says Done · in Status, and Undo gives the empty ring back", async () => {
  const user = userEvent.setup();
  const { transport } = makeTransport();
  const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
  const newer: WorkItemRecord = {
    ...overdue,
    id: OTHER_ID,
    title: "Skicka offerten",
    due_at: "2026-10-28T09:00:00.000Z",
  };
  renderAgenda([newer, older], transport);
  const group = () =>
    screen.getByRole("heading", { level: 3 }).closest("section")!;
  const lists = () => Array.from(group().querySelectorAll("ul.work-list"));
  const titlesOf = () =>
    Array.from(lists()[0]!.querySelectorAll("li[data-agenda-key]")).map(
      (li) => li.querySelector(".work-agenda-body button")?.textContent,
    );
  // Oldest first, both open: one list, and the heading counts two.
  expect(lists()).toHaveLength(1);
  expect(titlesOf()).toEqual([older.title, newer.title]);
  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("(2)");
  expect(rowOf(older.title)).not.toHaveAttribute("data-undo");
  const metaBefore = rowOf(older.title).querySelector(".work-card-meta");
  expect(metaBefore).not.toBeNull();
  const metaText = metaBefore!.textContent;
  await user.click(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: older.title }),
    }),
  );
  const line = await undoLineOf(older.title);
  // The row stays on its place, in the same list, and the count follows the open rows at once (it is the
  // number "Flytta n" moves; a row under Ångra is not counted).
  expect(line).toHaveTextContent("Done · in Status");
  expect(workEn.agendaDoneInStatus).toBe("Done · in Status");
  expect(workSv.agendaDoneInStatus).toBe("Klar · finns i Status");
  expect(lists()).toHaveLength(1);
  expect(titlesOf()).toEqual([older.title, newer.title]);
  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("(1)");
  expect(rowOf(older.title)).toHaveAttribute("data-undo", "on");
  expect(rowOf(newer.title)).not.toHaveAttribute("data-undo");
  // The ring is the same node and keeps focus, now saying that it opens the Task again.
  expect(document.activeElement).toBe(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaReopen, { title: older.title }),
    }),
  );
  // Undo gives the empty ring and the meta line back, and the row counts again.
  await user.click(
    within(rowOf(older.title)).getByRole("button", { name: workEn.agendaUndo }),
  );
  await waitFor(() =>
    expect(rowOf(older.title)).not.toHaveAttribute("data-undo"),
  );
  expect(
    screen.getByRole("button", {
      name: fillLabel(workEn.agendaComplete, { title: older.title }),
    }),
  ).toBeInTheDocument();
  expect(rowOf(older.title).querySelector(".work-card-meta")).toHaveTextContent(
    metaText,
  );
  expect(lists()).toHaveLength(1);
  expect(titlesOf()).toEqual([older.title, newer.title]);
  expect(screen.getByRole("heading", { level: 3 })).toHaveTextContent("(2)");
});

it("a date move of an overdue row stands on its place for its Undo, and the count drops when the Undo has run out", async () => {
  vi.useFakeTimers();
  setReducedMotion(true);
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, older], transport);
    const heading = () =>
      screen.getByRole("heading", { level: 3, name: /^Overdue/ });
    const lists = () =>
      Array.from(
        heading().closest("section")!.querySelectorAll("ul.work-list"),
      );
    fireEvent.contextMenu(rowOf(older.title));
    const dates = within(
      within(rowOf(older.title)).getByRole("group", {
        name: workEn.rescheduleGroup,
      }),
    );
    fireEvent.click(dates.getByRole("button", { name: workEn.triageTomorrow }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Moved: the row stands in the list it was in, with its Undo, and the heading counts open rows only.
    expect(rowOf(older.title)).toHaveAttribute("data-undo", "on");
    expect(rowOf(older.title)).toHaveTextContent("Moved to tomorrow");
    expect(lists()).toHaveLength(1);
    expect(heading()).toHaveTextContent("(1)");
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    // The Undo ran out: the row sinks under the group's line, the count stays. A moved row does not fold away.
    expect(lists()).toHaveLength(2);
    expect(lists()[1]).toHaveClass("work-agenda-handled");
    expect(lists()[1]).toHaveTextContent(older.title);
    expect(heading()).toHaveTextContent("(1)");
    expect(rowOf(older.title)).not.toHaveAttribute("data-undo");
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

/** Marks a row done from its ring and lets the write settle under fake timers (waitFor would hang there). */
async function doneFromRing(title: string) {
  // A click focuses its ring in a browser; fireEvent does not, so focus the ring first (the focus is read below).
  const ring = screen.getByRole("button", {
    name: fillLabel(workEn.agendaComplete, { title }),
  });
  act(() => ring.focus());
  fireEvent.click(ring);
  await act(async () => {
    await vi.advanceTimersByTimeAsync(0);
  });
}

/** Sets the host's reduced-motion answer for the agenda's fold, as a media query would give it. */
function setReducedMotion(reduce: boolean) {
  vi.stubGlobal("matchMedia", (query: string) => ({
    matches: reduce && query.includes("prefers-reduced-motion"),
    media: query,
    onchange: null,
    addEventListener: () => undefined,
    removeEventListener: () => undefined,
    addListener: () => undefined,
    removeListener: () => undefined,
    dispatchEvent: () => false,
  }));
}

/** The agenda's rows, in the order they stand in the DOM (a row that is folding away still stands). */
function agendaRows() {
  return Array.from(document.querySelectorAll("li[data-agenda-key]"));
}

it("a done row of Försenade folds away 200 ms after its Undo has run out, the count drops, and focus goes to the row above", async () => {
  vi.useFakeTimers();
  setReducedMotion(false);
  // The row's focus moves in the next animation frame; run it at once so the test can read it.
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  });
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, older], transport);
    const heading = () =>
      screen.getByRole("heading", { level: 3, name: /^Overdue/ });
    expect(heading()).toHaveTextContent("(2)");
    expect(agendaRows()).toHaveLength(2);

    await doneFromRing(older.title);
    // Done, the row stands on its place under Ångra and the count already left it out.
    expect(heading()).toHaveTextContent("(1)");
    expect(agendaRows()).toHaveLength(2);

    // Its Undo runs out: the row folds for 200 ms (data-leaving), then it has left the group.
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    expect(rowOf(older.title)).toHaveAttribute("data-leaving");
    act(() => {
      vi.advanceTimersByTime(199);
    });
    expect(agendaRows()).toHaveLength(2);
    // The count did not wait for the fold.
    expect(heading()).toHaveTextContent("(1)");
    act(() => {
      vi.advanceTimersByTime(1);
    });
    expect(agendaRows()).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: older.title }),
    ).not.toBeInTheDocument();
    expect(heading()).toHaveTextContent("(1)");
    // Focus was on the done row's ring, so it moves to the open row above, to its ring.
    expect(document.activeElement).toBe(
      screen.getByRole("button", {
        name: fillLabel(workEn.agendaComplete, { title: newer.title }),
      }),
    );
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("with reduced motion a done row of Försenade leaves the group at once when its Undo has run out", async () => {
  vi.useFakeTimers();
  setReducedMotion(true);
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, older], transport);
    await doneFromRing(older.title);
    expect(agendaRows()).toHaveLength(2);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    // No fold and no 200 ms wait: the row is gone with its Undo.
    expect(agendaRows()).toHaveLength(1);
    expect(
      screen.queryByRole("button", { name: older.title }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("heading", { level: 3, name: /^Overdue/ }),
    ).toHaveTextContent("(1)");
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("a row that has folded away is gathered in the folded Klar idag (n) last in the Agenda, and a tap on its ring brings it back to its group", async () => {
  vi.useFakeTimers();
  setReducedMotion(true);
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    renderAgenda([older, todayTask], transport);
    // Nothing is done here yet: no fold.
    expect(screen.queryByText(/Done here/)).not.toBeInTheDocument();
    await doneFromRing(older.title);
    // While Ångra shows, the row is still in its group and the fold does not count it.
    expect(screen.queryByText(/Done here/)).not.toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    const fold = screen.getByRole("button", { name: /^Done here/ });
    expect(fold).toHaveTextContent("Done here (1)");
    expect(fold).toHaveAttribute("aria-expanded", "false");
    // The same markup as Status's Klar section: a section with a heading whose button folds it.
    expect(fold).toHaveClass("sk-fold");
    expect(fold).toHaveTextContent("Since you opened the agenda");
    expect(fold.closest("h3")).not.toBeNull();
    expect(fold.closest("section")).toHaveClass("work-column");
    // It stands after every group (and before the tip).
    const sections = Array.from(document.querySelectorAll("article > section"));
    expect(sections[sections.length - 1]).toBe(fold.closest("section"));
    // Folded, it shows no row.
    expect(
      screen.queryByRole("button", { name: older.title }),
    ).not.toBeInTheDocument();
    fireEvent.click(fold);
    expect(fold).toHaveAttribute("aria-expanded", "true");
    const done = rowOf(older.title);
    expect(fold.closest("section")).toContainElement(done);
    // The ring of a done row says that it opens the Task again; the meta line gives no date for a done Task.
    fireEvent.click(
      within(done).getByRole("button", {
        name: fillLabel(workEn.agendaReopen, { title: older.title }),
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    // Open again: the row is back in Overdue (with the Undo of that move), and the fold is gone.
    expect(screen.queryByText(/Done here/)).not.toBeInTheDocument();
    const group = screen
      .getByRole("heading", { level: 3, name: /^Overdue/ })
      .closest("section")!;
    expect(group).toContainElement(rowOf(older.title));
    // Marked done again, the row waits out its own Undo before it leaves.
    fireEvent.click(
      within(rowOf(older.title)).getByRole("button", {
        name: fillLabel(workEn.agendaComplete, { title: older.title }),
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(group).toContainElement(rowOf(older.title));
    expect(rowOf(older.title)).toHaveAttribute("data-undo", "on");
    expect(screen.queryByText(/Done here/)).not.toBeInTheDocument();
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("Undo of a reopen from Klar idag puts the row back in Klar idag, not in its old group", async () => {
  vi.useFakeTimers();
  setReducedMotion(true);
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    renderAgenda([older, todayTask], transport);
    await doneFromRing(older.title);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    fireEvent.click(screen.getByRole("button", { name: /^Done here/ }));
    // Open the Task again from Klar idag: it is back in Overdue with the Undo of that move.
    fireEvent.click(
      within(rowOf(older.title)).getByRole("button", {
        name: fillLabel(workEn.agendaReopen, { title: older.title }),
      }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(screen.queryByText(/Done here/)).not.toBeInTheDocument();
    // Ångra: the Task is done again and stands in Klar idag, not in Overdue.
    fireEvent.click(screen.getByRole("button", { name: workEn.agendaUndo }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    const fold = screen.getByRole("button", { name: /^Done here/ });
    expect(fold).toHaveTextContent("Done here (1)");
    const overdueGroup = screen
      .getByRole("heading", { level: 3, name: /^Overdue/ })
      .closest("section")!;
    // The fold stayed open from before: the row stands in it, and not in the group it came from.
    expect(fold).toHaveAttribute("aria-expanded", "true");
    expect(fold.closest("section")).toContainElement(rowOf(older.title));
    expect(overdueGroup).not.toContainElement(rowOf(older.title));
    expect(overdueGroup).toHaveTextContent("(0)");
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("a read of the list shows again a row that folded away, so a Task open on the new list is not hidden", async () => {
  vi.useFakeTimers();
  setReducedMotion(true);
  try {
    const { transport, getWorkAgenda } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, older], transport);
    await doneFromRing(older.title);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    // Its Undo ran out: the done row has left its group.
    expect(agendaRows()).toHaveLength(1);
    fireEvent.click(screen.getByRole("button", { name: workEn.refresh }));
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(getWorkAgenda).toHaveBeenCalled();
    // The read clears the hidden row: it stands in the list again.
    expect(agendaRows()).toHaveLength(2);
    expect(
      screen.getByRole("button", { name: older.title }),
    ).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("the Undo of a due move on a Task already done does not fold its row away when the Undo runs out", async () => {
  vi.useFakeTimers();
  setReducedMotion(false);
  try {
    // The echo keeps the Task done: a due move leaves its status as it was.
    const updateTask = vi.fn(
      (id: string, version: number, changes: WorkTaskChanges) =>
        Promise.resolve({
          task: {
            id,
            title: "",
            status: "completed",
            due_at: changes.due_at ?? null,
            version: version + 1,
          },
        }),
    );
    const transport = {
      updateTask,
      getTask: vi.fn(),
      getWorkAgenda: vi.fn(),
    } as unknown as WorkTransport;
    const done: WorkItemRecord = {
      ...overdue,
      title: "Ring Anna",
      status: "completed",
    };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, done], transport);
    openRow(done.title);
    fireEvent.click(
      within(
        screen.getByRole("group", { name: workEn.rescheduleGroup }),
      ).getByRole("button", { name: workEn.triageTomorrow }),
    );
    await act(async () => {
      await vi.advanceTimersByTimeAsync(0);
    });
    expect(updateTask).toHaveBeenCalledTimes(1);
    expect(
      within(rowOf(done.title)).getByRole("button", {
        name: workEn.agendaUndo,
      }),
    ).toBeInTheDocument();
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    // The Undo ran out, but the change was a date move, not "Klar": the row keeps its place.
    expect(rowOf(done.title)).not.toHaveAttribute("data-leaving");
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(agendaRows()).toHaveLength(2);
    expect(rowOf(done.title)).toBeInTheDocument();
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("focus that the user moved elsewhere while a done row folds away stays there; it does not jump to the row above", async () => {
  vi.useFakeTimers();
  setReducedMotion(false);
  // The row's focus moves in the next animation frame; run it at once so the test can read it.
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 0;
  });
  try {
    const { transport } = makeTransport();
    const older: WorkItemRecord = { ...overdue, title: "Ring Anna" };
    const newer: WorkItemRecord = {
      ...overdue,
      id: OTHER_ID,
      title: "Skicka offerten",
      due_at: "2026-10-28T09:00:00.000Z",
    };
    renderAgenda([newer, older], transport);
    await doneFromRing(older.title);
    act(() => {
      vi.advanceTimersByTime(UNDO_MS);
    });
    expect(rowOf(older.title)).toHaveAttribute("data-leaving");
    // The user moves focus out of the row during the 200 ms fold.
    const refresh = screen.getByRole("button", { name: workEn.refresh });
    act(() => refresh.focus());
    act(() => {
      vi.advanceTimersByTime(200);
    });
    expect(agendaRows()).toHaveLength(1);
    expect(document.activeElement).toBe(refresh);
  } finally {
    vi.useRealTimers();
    vi.unstubAllGlobals();
  }
});

it("the × closes a row's quick choices, is an icon button with no visible text, and leaves the focus on the row's title", async () => {
  const { transport, updateTask } = makeTransport();
  renderAgenda([overdue], transport, workSv);
  await openMenu(overdue.title, workSv);
  const row = within(rowOf(overdue.title));
  const close = row.getByRole("button", { name: workSv.closeMenu });
  expect(close).toHaveClass("work-agenda-menu-close");
  expect(close.textContent).toBe("");
  expect(close.querySelector("svg")).not.toBeNull();
  await userEvent.click(close);
  expect(row.queryByRole("group", { name: workSv.status })).toBeNull();
  expect(row.getByRole("button", { name: overdue.title })).toHaveFocus();
  expect(updateTask).not.toHaveBeenCalled();
});
