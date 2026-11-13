import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { NewTaskInput } from "@/features/work-app/tasks/new-task-input";
import {
  newTaskInputLabelsEn,
  newTaskInputLabelsFor,
  newTaskInputLabelsSv,
} from "@/features/work-app/tasks/new-task-input-labels";
import type {
  WorkAgendaPage,
  WorkBoardPage,
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkFullscreen } from "@/features/work-app/fullscreen/work-fullscreen";
import { workShellLabelsEn } from "@/features/work-app/shell/work-shell-labels";

const created: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Ring Anna fredag",
  status: "todo",
  due_at: null,
  version: 1,
  project_id: null,
  domain_id: null,
};

// The field is open here: NewTaskInput shows the shared CreateField while `open` is true. onClose is a
// stub, so the test owns when the field closes; the caller's + is not part of these unit cases.
function mountInput(
  createTask: WorkTransport["createTask"],
  onCreated = vi.fn(),
  onClose = vi.fn(),
) {
  render(
    <div className="sidekick-work">
      <NewTaskInput
        transport={{ createTask } as unknown as WorkTransport}
        labels={newTaskInputLabelsEn}
        workLabels={workEn}
        onCreated={onCreated}
        open
        onClose={onClose}
        showAdded
      />
    </div>,
  );
  return {
    field: screen.getByRole("textbox", { name: "New task" }),
    onCreated,
    onClose,
  };
}

describe("NewTaskInput", () => {
  it("creates a Task from the title alone and keeps the field open with the focus in it", async () => {
    const createTask = vi.fn().mockResolvedValue({ task: created });
    const { field, onCreated } = mountInput(createTask);
    expect(field).toHaveAttribute("placeholder", "New task, e.g. call Anna");
    expect(field).toHaveFocus();

    await userEvent.type(field, "  Ring Anna fredag ");
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));

    await waitFor(() => expect(onCreated).toHaveBeenCalledWith(created));
    expect(createTask).toHaveBeenCalledTimes(1);
    expect(createTask.mock.calls[0]![0]).toEqual({ title: "Ring Anna fredag" });
    expect(createTask.mock.calls[0]![1]).toMatch(/^[0-9a-f-]{36}$/);
    // The field empties and keeps the focus, so the next Task can be typed at once.
    expect(field).toHaveValue("");
    expect(field).toHaveFocus();
    expect(screen.getByRole("status")).toHaveTextContent(
      "Ring Anna fredag added to Unsorted",
    );
  });

  it('shows "Close" on an empty field: a tap closes it and creates nothing', async () => {
    const createTask = vi.fn().mockResolvedValue({ task: created });
    const { onClose } = mountInput(createTask);

    expect(
      screen.queryByRole("button", { name: "Add task" }),
    ).not.toBeInTheDocument();
    await userEvent.click(screen.getByRole("button", { name: "Close" }));

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(createTask).not.toHaveBeenCalled();
  });

  it("closes on Esc and creates nothing", async () => {
    const createTask = vi.fn().mockResolvedValue({ task: created });
    const { field, onClose } = mountInput(createTask);

    await userEvent.type(field, "{Escape}");

    expect(onClose).toHaveBeenCalledTimes(1);
    expect(createTask).not.toHaveBeenCalled();
  });

  it("ignores Enter on an empty field and creates once on Enter with text", async () => {
    const createTask = vi.fn().mockResolvedValue({ task: created });
    const { field, onCreated } = mountInput(createTask);
    await userEvent.type(field, "{Enter}");
    expect(createTask).not.toHaveBeenCalled();

    await userEvent.type(field, "Ring Anna fredag{Enter}");
    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(createTask).toHaveBeenCalledTimes(1);

    // The field is empty again after the create, so a further Enter creates nothing.
    await userEvent.type(field, "{Enter}");
    expect(createTask).toHaveBeenCalledTimes(1);
  });

  it("shows a failed create under the field and retries the same title with the same key", async () => {
    const createTask = vi
      .fn()
      .mockRejectedValueOnce(new Error("lost"))
      .mockResolvedValueOnce({ task: created });
    const { field, onCreated } = mountInput(createTask);
    await userEvent.type(field, "Ring Anna fredag");
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent("Couldn’t add “Ring Anna fredag”.");
    await userEvent.click(
      within(alert).getByRole("button", { name: workEn.retry }),
    );

    await waitFor(() => expect(onCreated).toHaveBeenCalledTimes(1));
    expect(createTask).toHaveBeenCalledTimes(2);
    expect(createTask.mock.calls[1]![0]).toEqual({ title: "Ring Anna fredag" });
    expect(createTask.mock.calls[1]![1]).toBe(createTask.mock.calls[0]![1]);
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names a refused create with the shared write text and offers no retry", async () => {
    const createTask = vi.fn().mockRejectedValue({ code: "forbidden" });
    const { field } = mountInput(createTask);
    await userEvent.type(field, "Ring Anna fredag");
    await userEvent.click(screen.getByRole("button", { name: "Add task" }));

    const alert = await screen.findByRole("alert");
    expect(alert).toHaveTextContent(workEn.forbiddenWrite);
    expect(within(alert).queryByRole("button")).toBeNull();
  });

  describe("with placeChoice", () => {
    const frame = {
      kind: "hierarchy" as const,
      truncated: false,
      nodes: [
        { kind: "domain" as const, id: "d1", parent_id: null, title: "Hem" },
        {
          kind: "project" as const,
          id: "p1",
          parent_id: "d1",
          title: "Renovering av köket",
          status: "active",
        },
      ],
    };

    function mountWithPlace(labels = newTaskInputLabelsEn, work = workEn) {
      // The server stores the typed title, so the receipt names it.
      const createTask = vi.fn((task: { title: string }) =>
        Promise.resolve({
          task: { ...created, title: task.title },
        }),
      );
      const getWorkHierarchy = vi.fn().mockResolvedValue(frame);
      render(
        <div className="sidekick-work">
          <NewTaskInput
            transport={
              { createTask, getWorkHierarchy } as unknown as WorkTransport
            }
            labels={labels}
            workLabels={work}
            onCreated={vi.fn()}
            open
            onClose={vi.fn()}
            showAdded
            placeChoice
          />
        </div>,
      );
      return { createTask, getWorkHierarchy };
    }

    it("creates in no place by default and says Unsorted", async () => {
      const { createTask } = mountWithPlace();
      await screen.findByRole("combobox", { name: "Filed under" });
      await userEvent.type(
        screen.getByRole("textbox", { name: "New task" }),
        "Måla taket{Enter}",
      );
      await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
      expect(createTask.mock.calls[0]![0]).toEqual({ title: "Måla taket" });
      expect(screen.getByRole("status")).toHaveTextContent(
        "Måla taket added to Unsorted",
      );
    });

    it("sends the chosen Project, names it in the receipt and keeps the choice for the next Task", async () => {
      const { createTask } = mountWithPlace();
      const picker = await screen.findByRole("combobox", {
        name: "Filed under",
      });
      await userEvent.selectOptions(picker, "project:p1");
      const field = screen.getByRole("textbox", { name: "New task" });
      await userEvent.type(field, "Måla taket{Enter}");
      await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
      expect(createTask.mock.calls[0]![0]).toEqual({
        title: "Måla taket",
        project_id: "p1",
      });
      expect(screen.getByRole("status")).toHaveTextContent(
        "Måla taket added to Renovering av köket",
      );
      expect(picker).toHaveValue("project:p1");

      await userEvent.type(field, "Laga lampan{Enter}");
      await waitFor(() => expect(createTask).toHaveBeenCalledTimes(2));
      expect(createTask.mock.calls[1]![0]).toEqual({
        title: "Laga lampan",
        project_id: "p1",
      });
    });

    it("sends a Domain as domain_id and states the receipt in Swedish", async () => {
      const { createTask } = mountWithPlace(newTaskInputLabelsSv, workSv);
      const picker = await screen.findByRole("combobox", { name: "Plats" });
      await userEvent.selectOptions(picker, "domain:d1");
      await userEvent.type(
        screen.getByRole("textbox", { name: "Ny uppgift" }),
        "Städa{Enter}",
      );
      await waitFor(() => expect(createTask).toHaveBeenCalledTimes(1));
      expect(createTask.mock.calls[0]![0]).toEqual({
        title: "Städa",
        domain_id: "d1",
      });
      expect(screen.getByRole("status")).toHaveTextContent(
        "Städa tillagd i Hem",
      );
    });

    it("reads the places only when asked for, not for a field without the row", () => {
      const getWorkHierarchy = vi.fn().mockResolvedValue(frame);
      render(
        <NewTaskInput
          transport={
            {
              createTask: vi.fn(),
              getWorkHierarchy,
            } as unknown as WorkTransport
          }
          labels={newTaskInputLabelsEn}
          workLabels={workEn}
          onCreated={vi.fn()}
          open
        />,
      );
      expect(screen.queryByRole("combobox")).toBeNull();
      expect(getWorkHierarchy).not.toHaveBeenCalled();
    });
  });

  it("renders no field while closed, only the empty live region", () => {
    render(
      <NewTaskInput
        transport={{ createTask: vi.fn() } as unknown as WorkTransport}
        labels={newTaskInputLabelsEn}
        workLabels={workEn}
        onCreated={vi.fn()}
        open={false}
        onClose={vi.fn()}
        showAdded
      />,
    );

    expect(screen.queryByRole("textbox")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByRole("status").textContent).toBe("");
  });

  it("has Swedish and English labels with the same keys, picked by the date locale", () => {
    expect(Object.keys(newTaskInputLabelsSv).sort()).toEqual(
      Object.keys(newTaskInputLabelsEn).sort(),
    );
    expect(newTaskInputLabelsFor(workSv.dateLocale)).toBe(newTaskInputLabelsSv);
    expect(newTaskInputLabelsFor(workEn.dateLocale)).toBe(newTaskInputLabelsEn);
    expect(newTaskInputLabelsSv.placeholder).toBe(
      "Ny uppgift, t.ex. ring Anna",
    );
    expect(newTaskInputLabelsSv.add).toBe("Lägg till uppgift");
    expect(newTaskInputLabelsSv.close).toBe("Stäng");
    expect(newTaskInputLabelsSv.failed("Ring Anna fredag")).toBe(
      "Det gick inte att lägga till ”Ring Anna fredag”.",
    );
  });
});

describe("WorkFullscreen new-Task row", () => {
  const agendaPage: WorkAgendaPage = { items: [], next_cursor: null };
  const boardPage: WorkBoardPage = { columns: { todo: [] }, next_cursor: null };

  function fake() {
    const transport = {
      getWorkAgenda: vi.fn().mockResolvedValue(agendaPage),
      getWorkBoard: vi.fn().mockResolvedValue(boardPage),
      getWorkHierarchy: vi.fn(),
      listUnsortedTasks: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listDomains: vi.fn().mockResolvedValue([]),
      listContacts: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
      createTask: vi.fn().mockResolvedValue({ task: created }),
    };
    return transport;
  }

  it("keeps the new-Task field closed at rest, and New task opens it in the Agenda", async () => {
    const transport = fake();
    render(
      <WorkFullscreen
        transport={transport as unknown as WorkTransport}
        initial={{ kind: "agenda", filters: {}, page: agendaPage }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    const agenda = await screen.findByRole("region", { name: "Agenda" });
    expect(
      screen.queryByRole("textbox", { name: "New task" }),
    ).not.toBeInTheDocument();

    await userEvent.click(screen.getByRole("button", { name: "New task" }));

    expect(
      within(agenda).getByRole("textbox", { name: "New task" }),
    ).toHaveFocus();
    expect(screen.getByRole("button", { name: "New task" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("closes the field on Esc and gives the focus back to New task", async () => {
    const transport = fake();
    render(
      <WorkFullscreen
        transport={transport as unknown as WorkTransport}
        initial={{ kind: "agenda", filters: {}, page: agendaPage }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    await screen.findByRole("region", { name: "Agenda" });
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    expect(screen.getByRole("textbox", { name: "New task" })).toHaveFocus();

    await userEvent.keyboard("{Escape}");

    expect(
      screen.queryByRole("textbox", { name: "New task" }),
    ).not.toBeInTheDocument();
    const toggle = screen.getByRole("button", { name: "New task" });
    expect(toggle).toHaveFocus();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });

  it("shows a Task added on the agenda at once in its own group and reads the lists again", async () => {
    const transport = fake();
    render(
      <WorkFullscreen
        transport={transport as unknown as WorkTransport}
        initial={{ kind: "agenda", filters: {}, page: agendaPage }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    const agenda = await screen.findByRole("region", { name: "Agenda" });
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    const field = within(agenda).getByRole("textbox", { name: "New task" });
    await userEvent.type(field, "Ring Anna fredag");
    const agendaReads = transport.getWorkAgenda.mock.calls.length;
    const unsortedReads = transport.listUnsortedTasks.mock.calls.length;
    await userEvent.click(
      within(agenda).getByRole("button", { name: "Add task" }),
    );

    const group = await within(agenda).findByRole("region", {
      name: "Just added (1)",
    });
    expect(within(group).getByText("Ring Anna fredag")).toBeVisible();
    expect(within(group).getByText("No date")).toBeVisible();
    await waitFor(() =>
      expect(transport.getWorkAgenda.mock.calls.length).toBeGreaterThan(
        agendaReads,
      ),
    );
    expect(transport.listUnsortedTasks.mock.calls.length).toBeGreaterThan(
      unsortedReads,
    );
  });

  it("reads the board again in place after a Task is added on the board", async () => {
    const transport = fake();
    render(
      <WorkFullscreen
        transport={transport as unknown as WorkTransport}
        initial={{ kind: "board", filters: {}, page: boardPage }}
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    const board = await screen.findByRole("region", { name: "Status" });
    await userEvent.click(screen.getByRole("button", { name: "New task" }));
    const boardReads = transport.getWorkBoard.mock.calls.length;

    await userEvent.type(
      within(board).getByRole("textbox", { name: "New task" }),
      "Ring Anna fredag{Enter}",
    );

    await waitFor(() =>
      expect(transport.getWorkBoard.mock.calls.length).toBeGreaterThan(
        boardReads,
      ),
    );
    expect(
      within(board).getByText("Ring Anna fredag added to Unsorted"),
    ).toBeVisible();
  });

  it("disables New task while the tab's first read failed, and a press opens nothing", async () => {
    const transport = fake();
    transport.getWorkBoard.mockRejectedValue(new Error("down"));
    render(
      <WorkFullscreen
        transport={transport as unknown as WorkTransport}
        startTab="board"
        labels={workEn}
        shellLabels={workShellLabelsEn}
      />,
    );
    // The first read has failed when the error notice shows; until then + is off as well.
    await screen.findByRole("alert");
    const toggle = screen.getByRole("button", { name: "New task" });
    expect(toggle).toHaveAttribute("aria-disabled", "true");

    await userEvent.click(toggle);

    expect(
      screen.queryByRole("textbox", { name: "New task" }),
    ).not.toBeInTheDocument();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
  });
});
