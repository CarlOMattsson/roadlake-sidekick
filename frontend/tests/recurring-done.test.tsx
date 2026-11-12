import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { fillLabel } from "@/features/work-app/agenda-undo";
import { isRecurringCycle } from "@/features/work-app/agenda-parts/agenda-helpers";
import { RecordMeta } from "@/features/work-app/board-card";
import { workEn, workSv } from "@/features/work-app/labels";
import {
  taskPlaceLabelsEn,
  taskPlaceLabelsSv,
} from "@/features/work-app/task-place-labels";
import type {
  WorkItemRecord,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport";
import { WorkView } from "@/features/work-app/work-view";
import {
  DUE,
  NOW,
  overdue,
  renderAgenda,
  rowOf,
} from "./helpers/agenda-triage-fixtures";

// uc-1: a recurring Task marked done comes back "todo" with its next date (the server records the cycle in
// last_completed_at). The view must say so ("Klar · nästa: …") with an Ångra that writes the old date back.

const monthly = {
  frequency: "monthly" as const,
  interval: 1,
  weekdays: [],
  day_of_month: null,
  until: null,
};
const NEXT = "2026-11-27T09:00:00.000Z";

/** update_task as the server answers for a recurring Task: done reopens it at NEXT; a due change is echoed. */
function recurringUpdate() {
  return vi.fn((id: string, version: number, changes: WorkTaskChanges) =>
    Promise.resolve({
      task: {
        id,
        title: "Betala hyran",
        status: "todo",
        due_at:
          changes.due_at !== undefined
            ? changes.due_at
            : changes.status === "completed"
              ? NEXT
              : DUE,
        recurrence: monthly,
        last_completed_at:
          changes.status === "completed" ? "2026-10-29T09:00:00Z" : null,
        version: version + 1,
      } as WorkTask,
    }),
  );
}

describe("isRecurringCycle", () => {
  const reply = {
    status: "todo",
    due_at: NEXT,
    recurrence: monthly,
    last_completed_at: "2026-10-29T09:00:00Z",
  };
  it("is a cycle only for a reopened recurring Task with a new date", () => {
    expect(isRecurringCycle(reply, DUE)).toBe(true);
    expect(isRecurringCycle(reply, NEXT)).toBe(false);
    expect(isRecurringCycle({ ...reply, recurrence: null }, DUE)).toBe(false);
    expect(isRecurringCycle({ ...reply, status: "completed" }, DUE)).toBe(
      false,
    );
    expect(isRecurringCycle({ ...reply, last_completed_at: null }, DUE)).toBe(
      false,
    );
  });
});

describe("Agenda: done on a recurring Task", () => {
  it.each([
    ["no completion on record", null],
    ["an earlier completion on record", "2026-09-29T09:00:00Z"],
  ])(
    "says Done · next: <date> with Undo, which writes the old due date and completion back (%s)",
    async (_name, earlier) => {
      const user = userEvent.setup();
      const updateTask = recurringUpdate();
      const transport = {
        updateTask,
        getTask: vi.fn(),
        getWorkAgenda: vi.fn(() =>
          Promise.resolve({ items: [], next_cursor: null }),
        ),
      } as unknown as WorkTransport;
      const rent: WorkItemRecord = {
        ...overdue,
        recurrence: monthly,
        last_completed_at: earlier,
      };
      renderAgenda([rent], transport);

      await user.click(
        screen.getByRole("button", {
          name: fillLabel(workEn.agendaComplete, { title: rent.title }),
        }),
      );
      const row = within(rowOf(rent.title));
      expect(await row.findByRole("status")).toHaveTextContent(
        "Done · next: 27 Nov",
      );
      expect(updateTask).toHaveBeenCalledWith(
        rent.id,
        3,
        { status: "completed" },
        expect.any(String),
      );

      await user.click(row.getByRole("button", { name: workEn.agendaUndo }));
      await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
      expect(updateTask.mock.calls[1]?.[2]).toEqual({
        due_at: DUE,
        last_completed_at: earlier,
      });
      await waitFor(() =>
        expect(rowOf(rent.title)).not.toHaveAttribute("data-undo"),
      );
      // Back as it was: overdue again, open, with its repeat marker.
      expect(
        rowOf(rent.title).querySelector(".work-card-meta"),
      ).toHaveTextContent(/days? overdue/);
    },
  );

  it("speaks Swedish: Klar · nästa: 27 nov", async () => {
    const user = userEvent.setup();
    const transport = {
      updateTask: recurringUpdate(),
      getTask: vi.fn(),
      getWorkAgenda: vi.fn(() =>
        Promise.resolve({ items: [], next_cursor: null }),
      ),
    } as unknown as WorkTransport;
    const rent: WorkItemRecord = { ...overdue, recurrence: monthly };
    renderAgenda([rent], transport, workSv);
    await user.click(
      screen.getByRole("button", {
        name: fillLabel(workSv.agendaComplete, { title: rent.title }),
      }),
    );
    expect(
      await within(rowOf(rent.title)).findByRole("status"),
    ).toHaveTextContent("Klar · nästa: 27 nov");
  });
});

describe("The repeat marker in a row's meta", () => {
  it("names the rule after the time, in both languages", () => {
    const item: WorkItemRecord = { ...overdue, recurrence: monthly };
    const { container, rerender } = render(
      <RecordMeta item={item} labels={workSv} now={NOW} />,
    );
    expect(container.querySelector(".work-card-repeat")).toHaveTextContent(
      "varje månad",
    );
    expect(container.querySelector(".sk-repeat-icon")).toHaveAttribute(
      "aria-hidden",
      "true",
    );
    rerender(<RecordMeta item={item} labels={workEn} now={NOW} />);
    expect(container.querySelector(".work-card-repeat")).toHaveTextContent(
      "monthly",
    );
    rerender(
      <RecordMeta
        item={{ ...item, recurrence: null }}
        labels={workEn}
        now={NOW}
      />,
    );
    expect(container.querySelector(".work-card-repeat")).toBeNull();
  });

  it("shares its words with the repeat chip", () => {
    const every2 = { frequency: "weekly" as const, interval: 2 };
    expect(taskPlaceLabelsSv.repeatsShort(every2)).toBe("var 2:a vecka");
    expect(taskPlaceLabelsSv.repeats(every2)).toBe("Upprepas var 2:a vecka");
    expect(taskPlaceLabelsEn.repeatsShort(every2)).toBe("every 2 weeks");
    expect(taskPlaceLabelsEn.repeats({ ...every2, interval: 1 })).toBe(
      "Repeats weekly",
    );
  });
});

describe("Task view: Mark as done on a recurring Task", () => {
  it("shows Done · next: <date> under the button, and Undo writes the old date back", async () => {
    const user = userEvent.setup();
    const task: WorkTask = {
      id: overdue.id,
      title: "Betala hyran",
      status: "todo",
      due_at: DUE,
      version: 3,
      recurrence: monthly,
    };
    const updateTask = recurringUpdate();
    const work = {
      getTask: vi.fn().mockResolvedValue({ task }),
      listTaskContacts: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listTaskSteps: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listTaskExternalReferences: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      updateTask,
    } as unknown as WorkTransport;
    render(
      <WorkView
        transport={work}
        initial={{ kind: "task", id: task.id }}
        labels={workEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: workEn.markDone }),
    );
    const line = await screen.findByText(/^Done · next: /);
    expect(line).toHaveAttribute("role", "status");
    expect(line.closest(".work-task-cycle")).not.toBeNull();
    await user.click(
      within(line.closest(".work-task-cycle") as HTMLElement).getByRole(
        "button",
        { name: workEn.agendaUndo },
      ),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[1]?.[2]).toEqual({
      due_at: DUE,
      last_completed_at: null,
    });
    await waitFor(() =>
      expect(screen.queryByText(/^Done · next: /)).toBeNull(),
    );
  });
});
