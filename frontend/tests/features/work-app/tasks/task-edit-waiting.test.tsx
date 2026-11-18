import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workSv } from "@/features/work-app/shared/labels";
import {
  changedFields,
  dateInputValue,
  draftFromTask,
  TaskEditor,
  type DraftState,
} from "@/features/work-app/tasks/task-edit";
import type {
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";

const NOW = new Date("2026-11-18T12:00:00Z");
const ANDERS = "019f0000-0000-7000-8000-0000000000a9";

const idle: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Svar från Anders om bildformat",
  status: "todo",
  due_at: null,
  version: 3,
};
const waiting: WorkTask = {
  ...idle,
  waiting_since: "2026-11-13T09:00:00+01:00",
  follow_up_at: "2026-11-17T09:00:00+01:00",
  waiting_on_contact_id: ANDERS,
};

function stateOf(
  task: WorkTask,
  edit: Partial<ReturnType<typeof draftFromTask>>,
) {
  const base = draftFromTask(task);
  const state: DraftState = {
    base,
    values: { ...base, ...edit },
    dueIncomplete: false,
  };
  return state;
}

describe("the waiting fields of the Task editor", () => {
  it("sends nothing while they are untouched", () => {
    expect(changedFields(stateOf(waiting, {}), NOW)).toEqual({});
  });

  it("starts a wait with a Contact on the day chosen", () => {
    const changes = changedFields(
      stateOf(idle, { waitingSince: "2026-11-13", waitingContact: ANDERS }),
      NOW,
    );
    expect(dateInputValue(changes.waiting_since ?? null)).toBe("2026-11-13");
    expect(changes.waiting_on_contact_id).toBe(ANDERS);
    expect(changes.follow_up_at).toBeUndefined();
  });

  it("sends the follow-up day and empties it as null", () => {
    const set = changedFields(
      stateOf(waiting, { followUp: "2026-11-25" }),
      NOW,
    );
    expect(dateInputValue(set.follow_up_at ?? null)).toBe("2026-11-25");
    expect(changedFields(stateOf(waiting, { followUp: "" }), NOW)).toEqual({
      follow_up_at: null,
    });
  });

  it("ends the wait by emptying the person and the follow-up day with it", () => {
    expect(
      changedFields(
        stateOf(waiting, {
          waitingSince: "",
          followUp: "",
          waitingContact: "",
        }),
        NOW,
      ),
    ).toEqual({
      waiting_since: null,
      follow_up_at: null,
      waiting_on_contact_id: null,
    });
  });

  it("sends nothing for a partial date entry", () => {
    const state = stateOf(waiting, { followUp: "" });
    expect(changedFields({ ...state, waitingIncomplete: true }, NOW)).toEqual(
      {},
    );
  });
});

describe("the Task editor with the waiting fields", () => {
  function mount(task: WorkTask) {
    const onSave = vi.fn<(changes: WorkTaskChanges) => void>();
    const transport = {
      searchContacts: vi.fn().mockResolvedValue({
        items: [{ id: ANDERS, display_name: "Anders Berg" }],
        next_cursor: null,
      }),
    } as unknown as WorkTransport;
    render(
      <TaskEditor
        task={task}
        busy={false}
        saveFailed={false}
        onSave={onSave}
        onCancel={vi.fn()}
        labels={workSv}
        transport={transport}
        waitingName="Anders"
      />,
    );
    return { onSave };
  }

  it("shows who the Task waits on, since when and the follow-up day", () => {
    mount(waiting);
    expect(screen.getByText("Anders")).toBeInTheDocument();
    expect(screen.getByLabelText("Väntar sedan")).toHaveValue("2026-11-13");
    expect(screen.getByLabelText("Följ upp")).toHaveValue("2026-11-17");
  });

  it("saves a new follow-up day without sending the fields it left alone", async () => {
    const user = userEvent.setup();
    const { onSave } = mount(waiting);
    const day = screen.getByLabelText("Följ upp");
    await user.clear(day);
    await user.type(day, "2026-11-25");
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(onSave).toHaveBeenCalledTimes(1);
    const changes = onSave.mock.calls[0]?.[0] ?? {};
    expect(Object.keys(changes)).toEqual(["follow_up_at"]);
    expect(dateInputValue(changes.follow_up_at ?? null)).toBe("2026-11-25");
  });

  it("starts the wait today when a follow-up day is set on a Task that does not wait", async () => {
    const user = userEvent.setup();
    const { onSave } = mount(idle);
    await user.type(screen.getByLabelText("Följ upp"), "2026-11-25");
    await user.click(screen.getByRole("button", { name: "Spara" }));
    const changes = onSave.mock.calls[0]?.[0] ?? {};
    expect(changes.waiting_since).toEqual(expect.any(String));
    expect(dateInputValue(changes.follow_up_at ?? null)).toBe("2026-11-25");
  });

  it("ends the wait with one button", async () => {
    const user = userEvent.setup();
    const { onSave } = mount(waiting);
    await user.click(
      screen.getByRole("button", { name: "Väntar inte längre" }),
    );
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(onSave).toHaveBeenCalledWith({
      waiting_since: null,
      follow_up_at: null,
      waiting_on_contact_id: null,
    });
  });

  it("changes the Contact from the search without saving the form on Enter", async () => {
    const user = userEvent.setup();
    const { onSave } = mount(waiting);
    await user.click(screen.getByRole("button", { name: "Byt person" }));
    await user.type(screen.getByRole("searchbox"), "Anders{Enter}");
    expect(onSave).not.toHaveBeenCalled();
    await user.click(
      await screen.findByRole("button", { name: "Anders Berg" }),
    );
    await user.click(screen.getByRole("button", { name: "Ta bort kontakt" }));
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(onSave).toHaveBeenCalledWith({ waiting_on_contact_id: null });
  });
});
