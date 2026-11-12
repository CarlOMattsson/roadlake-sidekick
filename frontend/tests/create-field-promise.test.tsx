import {
  act,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { hierarchyDetailLabelsFor } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn } from "@/features/work-app/shared/labels";
import { NewTaskInput } from "@/features/work-app/tasks/new-task-input";
import { newTaskInputLabelsEn } from "@/features/work-app/tasks/new-task-input-labels";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import type {
  WorkContactsFrame,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// The create field empties its text only when onCreate answers something other than false. These cases
// check that NewContact (A) and NewTaskInput (B) answer with the real outcome of their write.

const dl = hierarchyDetailLabelsFor(workEn.dateLocale);

const emptyFrame: WorkContactsFrame = {
  kind: "contacts",
  q: "",
  includeArchived: false,
  page: { items: [], next_cursor: null, q: "", includeArchived: false },
};

function renderContacts(createContact: ReturnType<typeof vi.fn>) {
  const onOpen = vi.fn();
  render(
    <ContactsView
      frame={emptyFrame}
      onChange={vi.fn()}
      transport={
        { listContacts: vi.fn(), createContact } as unknown as WorkTransport
      }
      labels={workEn}
      moves={0}
      onOpen={onOpen}
    />,
  );
  return { onOpen };
}

describe("NewContact keeps the name unless the Contact was created (A)", () => {
  it("keeps the name when the write fails and empties the field when it succeeds", async () => {
    const user = userEvent.setup();
    const createContact = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        contact: { id: "contact-bo", display_name: "Bo Berg" },
      });
    const { onOpen } = renderContacts(createContact);
    await user.click(screen.getByRole("button", { name: workEn.newContact }));
    const name = screen.getByRole("textbox", { name: workEn.newContact });

    await user.type(name, "Bo Berg{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      workEn.contactCreateFailed,
    );
    expect(name).toHaveValue("Bo Berg");

    // The same name, sent again from the field, creates the Contact and empties the field.
    await user.keyboard("{Enter}");
    await waitFor(() =>
      expect(onOpen).toHaveBeenCalledWith({
        kind: "contact",
        id: "contact-bo",
      }),
    );
    expect(name).toHaveValue("");
    expect(createContact).toHaveBeenCalledTimes(2);
  });

  it("keeps a name over the limit in the field and sends nothing", async () => {
    const user = userEvent.setup();
    const createContact = vi.fn();
    renderContacts(createContact);
    await user.click(screen.getByRole("button", { name: workEn.newContact }));
    const name = screen.getByRole("textbox", { name: workEn.newContact });
    fireEvent.change(name, { target: { value: "x".repeat(201) } });

    await user.click(screen.getByRole("button", { name: dl.add }));

    expect(screen.getByRole("alert")).toHaveTextContent(workEn.nameTooLong);
    expect(name).toHaveValue("x".repeat(201));
    expect(createContact).not.toHaveBeenCalled();
  });
});

const created = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Ring Anna",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  domain_id: null,
} as WorkTask;

function inputView(
  createTask: ReturnType<typeof vi.fn>,
  onCreated: (task: WorkTask) => void,
  open: boolean,
) {
  return (
    <div className="sidekick-work">
      <NewTaskInput
        transport={{ createTask } as unknown as WorkTransport}
        labels={newTaskInputLabelsEn}
        workLabels={workEn}
        onCreated={onCreated}
        open={open}
        onClose={vi.fn()}
        showAdded
      />
    </div>
  );
}

describe("NewTaskInput keeps the title unless the Task was created (B)", () => {
  it("keeps the title when the write fails and empties the field when it succeeds", async () => {
    const user = userEvent.setup();
    const createTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ task: created });
    const onCreated = vi.fn();
    render(inputView(createTask, onCreated, true));
    const field = screen.getByRole("textbox", { name: "New task" });

    await user.type(field, "Ring Anna{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      newTaskInputLabelsEn.failed("Ring Anna"),
    );
    expect(field).toHaveValue("Ring Anna");

    await user.keyboard("{Enter}");
    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    expect(field).toHaveValue("");
    expect(createTask).toHaveBeenCalledTimes(2);
    expect(createTask.mock.calls[1]![1]).toBe(createTask.mock.calls[0]![1]);
  });

  it("creates one Task for two quick calls with the same title, even from a new field", async () => {
    const user = userEvent.setup();
    let answer!: (value: { task: WorkTask }) => void;
    const createTask = vi.fn().mockImplementationOnce(
      () =>
        new Promise<{ task: WorkTask }>((resolve) => {
          answer = resolve;
        }),
    );
    const onCreated = vi.fn();
    const { rerender } = render(inputView(createTask, onCreated, true));

    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Ring Anna{Enter}",
    );
    expect(createTask).toHaveBeenCalledTimes(1);

    // Esc or × unmounts the field while the write is pending; + opens a new one with no guard of its own.
    rerender(inputView(createTask, onCreated, false));
    rerender(inputView(createTask, onCreated, true));
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Ring Anna{Enter}",
    );

    expect(createTask).toHaveBeenCalledTimes(1);
    act(() => answer({ task: created }));
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
  });

  it("lets a different title be written while the first one is pending", async () => {
    const user = userEvent.setup();
    const createTask = vi.fn<
      (input: { title: string }) => Promise<{ task: WorkTask }>
    >(() => new Promise(() => {}));
    const { rerender } = render(inputView(createTask, vi.fn(), true));

    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Ring Anna{Enter}",
    );
    rerender(inputView(createTask, vi.fn(), false));
    rerender(inputView(createTask, vi.fn(), true));
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Köp mjölk{Enter}",
    );

    expect(createTask).toHaveBeenCalledTimes(2);
    expect(createTask.mock.calls[1]![0]).toEqual({ title: "Köp mjölk" });
  });

  it("keeps one key per title while another title is started in between", async () => {
    const user = userEvent.setup();
    const createTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("lost answer for A"))
      .mockRejectedValueOnce(new Error("lost answer for B"))
      .mockResolvedValueOnce({ task: created });
    const { rerender } = render(inputView(createTask, vi.fn(), true));
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Ring Anna{Enter}",
    );
    await screen.findByRole("alert");
    rerender(inputView(createTask, vi.fn(), false));
    rerender(inputView(createTask, vi.fn(), true));
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "Köp mjölk{Enter}",
    );
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent("Köp mjölk"),
    );
    // A is written again (typed again): it must carry A's first key, not B's and not a new one.
    await user.type(
      screen.getByRole("textbox", { name: "New task" }),
      "{Control>}a{/Control}Ring Anna{Enter}",
    );
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(3));
    expect(createTask.mock.calls[2]![1]).toBe(createTask.mock.calls[0]![1]);
    expect(createTask.mock.calls[1]![1]).not.toBe(createTask.mock.calls[0]![1]);
  });

  it("retry empties the field only while it still holds the retried title", async () => {
    const user = userEvent.setup();
    const createTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ task: created });
    render(inputView(createTask, vi.fn(), true));
    const field = screen.getByRole("textbox", { name: "New task" });
    await user.type(field, "Ring Anna{Enter}");
    await screen.findByRole("alert");
    // A new draft is typed over the failed title; Retry then succeeds for A.
    await user.clear(field);
    await user.type(field, "Köp mjölk");
    await user.click(screen.getByRole("button", { name: workEn.retry }));
    await waitFor(() => expect(createTask).toHaveBeenCalledTimes(2));
    await screen.findByText(
      newTaskInputLabelsEn.added("Ring Anna", "Unsorted"),
    );
    expect(screen.getByRole("textbox", { name: "New task" })).toHaveValue(
      "Köp mjölk",
    );
  });

  it("retry that succeeds with the title still in the field empties it, so Enter makes no second Task (N1)", async () => {
    const user = userEvent.setup();
    const createTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({ task: created });
    render(inputView(createTask, vi.fn(), true));
    const field = screen.getByRole("textbox", { name: "New task" });
    await user.type(field, "Ring Anna{Enter}");
    await screen.findByRole("alert");
    await user.click(screen.getByRole("button", { name: workEn.retry }));
    await screen.findByText(
      newTaskInputLabelsEn.added("Ring Anna", "Unsorted"),
    );
    expect(screen.getByRole("textbox", { name: "New task" })).toHaveValue("");
    expect(createTask).toHaveBeenCalledTimes(2);
  });

  it("a Contact retry that succeeds empties the field (N1)", async () => {
    const user = userEvent.setup();
    const createContact = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockResolvedValueOnce({
        contact: { id: "contact-bo", display_name: "Bo Berg" },
      });
    renderContacts(createContact);
    await user.click(screen.getByRole("button", { name: workEn.newContact }));
    await user.type(
      screen.getByRole("textbox", { name: workEn.newContact }),
      "Bo Berg{Enter}",
    );
    await user.click(await screen.findByRole("button", { name: workEn.retry }));
    await waitFor(() => expect(createContact).toHaveBeenCalledTimes(2));
    await waitFor(() =>
      expect(
        screen.getByRole("textbox", { name: workEn.newContact }),
      ).toHaveValue(""),
    );
  });
});
