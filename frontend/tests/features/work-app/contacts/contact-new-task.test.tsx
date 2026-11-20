// A Contact's own "new Task for her": a + beside Tasks (an action row when she has none) that opens the Work create
// field with her linked, keeps it open for the next one, and reads her again so the Task shows in her list.
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { NewTaskInput } from "@/features/work-app/tasks/new-task-input";
import { newTaskInputLabelsEn } from "@/features/work-app/tasks/new-task-input-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  contactsRoomLabelsEn,
  contactsRoomLabelsSv,
} from "@/features/work-app/contacts/contacts-room-labels";
import type {
  WorkContactRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  KEY,
  anna,
  annaTasks,
  contactRoot,
  keyOf,
  newTask,
  transport,
} from "@tests/helpers/work-app-fixtures";

function contextOf(
  contact: WorkContactRecord,
  tasks: typeof annaTasks = annaTasks,
) {
  return Promise.resolve({
    contact,
    projects: { items: [], next_cursor: null },
    tasks: { items: tasks, next_cursor: null },
  });
}

function mount(
  overrides: Partial<WorkTransport> = {},
  labels: typeof workEn = workEn,
) {
  const createTask = vi.fn().mockResolvedValue({
    task: { ...newTask, title: "Skicka offert", project_id: null },
  });
  const work = transport({ createTask, ...overrides });
  render(contactRoot(work, labels));
  return { work, createTask };
}

const plusName = contactsRoomLabelsEn.newTaskFor("Anna");

describe("a Contact's new Task", () => {
  it("has the same words in Swedish and English", () => {
    expect(contactsRoomLabelsSv.newTaskFor("Anna")).toBe("Ny uppgift för Anna");
    expect(plusName).toBe("New task for Anna");
  });

  it("shows a + beside the Tasks heading when she has Tasks, and opens the field under it", async () => {
    const user = userEvent.setup();
    mount();
    const plus = await screen.findByRole("button", { name: plusName });
    expect(plus).toHaveClass("sk-iconbtn");
    expect(plus).toHaveAttribute("aria-expanded", "false");
    expect(plus.previousElementSibling).toHaveTextContent(workEn.tasks);

    await user.click(plus);
    const field = screen.getByRole("textbox", { name: "New task" });
    expect(plus).toHaveAttribute("aria-expanded", "true");
    expect(plus.getAttribute("aria-controls")).toBe(
      field.closest(".work-new-task")?.id,
    );
    expect(field).toHaveFocus();
  });

  it("offers an action row where the Tasks would stand when she has none", async () => {
    const user = userEvent.setup();
    mount({
      getContactContext: vi.fn(() => contextOf(anna, [])),
    });
    const row = await screen.findByRole("button", { name: plusName });
    expect(row).toHaveClass("sk-action-row");
    expect(row).toHaveTextContent(plusName);
    expect(
      screen.queryByRole("heading", { name: workEn.tasks }),
    ).not.toBeInTheDocument();

    await user.click(row);
    expect(screen.getByRole("textbox", { name: "New task" })).toHaveFocus();
    // The field stands in the row's place; Esc gives the row and the focus back.
    expect(
      screen.queryByRole("button", { name: plusName }),
    ).not.toBeInTheDocument();
    await user.keyboard("{Escape}");
    await waitFor(() =>
      expect(screen.getByRole("button", { name: plusName })).toHaveFocus(),
    );
  });

  it("creates the Task linked to her with Enter, reads her again and keeps the field open", async () => {
    const user = userEvent.setup();
    const { work, createTask } = mount();
    await user.click(await screen.findByRole("button", { name: plusName }));
    const reads = (work.getContactContext as ReturnType<typeof vi.fn>).mock
      .calls.length;
    const field = screen.getByRole("textbox", { name: "New task" });
    await user.type(field, "Skicka offert{Enter}");

    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
    expect(createTask.mock.calls[0]?.[0]).toEqual({
      title: "Skicka offert",
      contact_ids: [anna.id],
    });
    expect(keyOf(createTask, 0)).toMatch(KEY);
    await waitFor(() =>
      expect(work.getContactContext).toHaveBeenCalledTimes(reads + 1),
    );
    // Open for the next Task, with the caret still in it (the frame's focus on its heading does not take it).
    await waitFor(() =>
      expect(screen.getByRole("textbox", { name: "New task" })).toHaveFocus(),
    );
    expect(screen.getByRole("textbox", { name: "New task" })).toHaveValue("");
  });

  it("closes with Esc and gives the focus back to the +", async () => {
    const user = userEvent.setup();
    mount();
    const plus = await screen.findByRole("button", { name: plusName });
    await user.click(plus);
    await user.keyboard("{Escape}");
    await waitFor(() => expect(plus).toHaveFocus());
    expect(
      screen.queryByRole("textbox", { name: "New task" }),
    ).not.toBeInTheDocument();
  });

  it("offers nothing for an archived Contact", async () => {
    const archived = {
      ...anna,
      archived: true,
      archived_at: "2026-11-01T10:00:00Z",
    };
    mount({ getContactContext: vi.fn(() => contextOf(archived)) });
    await screen.findByRole("heading", { name: workEn.tasks });
    expect(
      screen.queryByRole("button", { name: plusName }),
    ).not.toBeInTheDocument();
  });

  it("offers nothing on a host without create_task", async () => {
    mount({
      supportsTool: (name: string) => name !== "create_task",
    });
    await screen.findByRole("heading", { name: workEn.tasks });
    expect(
      screen.queryByRole("button", { name: plusName }),
    ).not.toBeInTheDocument();
  });

  it("speaks Swedish with the Swedish labels", async () => {
    mount({}, workSv);
    expect(
      await screen.findByRole("button", {
        name: contactsRoomLabelsSv.newTaskFor("Anna"),
      }),
    ).toBeInTheDocument();
  });

  it("keys the same title for two Contacts apart, and the same title for one Contact alike", async () => {
    const user = userEvent.setup();
    const createTask = vi.fn().mockRejectedValue(new Error("no answer"));
    const field = (ids: string[]) => (
      <div className="sidekick-work">
        <NewTaskInput
          transport={{ createTask } as unknown as WorkTransport}
          labels={newTaskInputLabelsEn}
          workLabels={workEn}
          onCreated={vi.fn()}
          fields={{ contact_ids: ids }}
          open
        />
      </div>
    );
    const view = render(field(["a"]));
    const input = screen.getByRole("textbox", { name: "New task" });
    await user.type(input, "Ring{Enter}");
    await user.type(input, "{Enter}");
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(2));
    expect(keyOf(createTask, 1)).toBe(keyOf(createTask, 0));

    view.rerender(field(["b"]));
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "{Enter}",
    );
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(3));
    expect(keyOf(createTask, 2)).not.toBe(keyOf(createTask, 0));
  });
});
