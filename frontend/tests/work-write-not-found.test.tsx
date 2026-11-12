import {
  act,
  render,
  renderHook,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WriteNotice } from "@/features/work-app/shared/manage-controls";
import { failureNotice, NoticeView } from "@/features/work-app/board/board";
import { cardLabelsSv } from "@/features/work-app/shared/card-labels";
import { CreateParentTask } from "@/features/work-app/hierarchy/parent-task-create";
import { ContactsView } from "@/features/work-app/contacts/contacts-list";
import {
  hierarchyDetailLabelsEn,
  hierarchyDetailLabelsSv,
} from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import {
  taskStatusLabel,
  workEn,
  workSv,
} from "@/features/work-app/shared/labels";
import {
  manageLabelsEn,
  manageLabelsSv,
} from "@/features/work-app/shared/manage-labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import { useWorkWrite } from "@/features/work-app/shared/use-work-write";
import {
  WorkCard,
  type CardStatusWriter,
} from "@/features/work-app/inline/work-card";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  writeFailure,
  type WorkCardFrame,
  type WorkContactsFrame,
  type WorkItemRecord,
  type WorkStep,
  type WorkTask,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * A write whose record no longer exists (for example removed in another chat) is its own kind:
 * the text explains it, there is no Try again, and the idempotency key is released so a later
 * attempt is a new write.
 */

describe("writeFailure", () => {
  it("sorts a not_found refusal into its own kind", () => {
    expect(writeFailure({ code: "not_found" })).toBe("not_found");
  });

  it("keeps the other refusals and treats unknown errors as retryable", () => {
    expect(writeFailure({ code: "conflict" })).toBe("conflict");
    expect(writeFailure({ code: "forbidden" })).toBe("forbidden");
    expect(writeFailure({ code: "validation_error" })).toBe("invalid");
    expect(writeFailure({ code: "internal_error" })).toBe("failed");
    expect(writeFailure(new Error("network"))).toBe("failed");
    expect(writeFailure(undefined)).toBe("failed");
  });
});

describe("not_found without Try again", () => {
  it("NoticeView (board, agenda, To sort) shows the text in Swedish and no Försök igen", () => {
    const onRetry = vi.fn();
    render(
      <NoticeView
        notice={failureNotice({ code: "not_found" }, "move")}
        labels={workSv}
        onReload={vi.fn()}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(workSv.notFound);
    expect(workSv.notFound).toBe(
      "Den finns inte längre. Den kan ha tagits bort i en annan chatt.",
    );
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("NoticeView shows the English text", () => {
    render(
      <NoticeView
        notice={failureNotice({ code: "not_found" }, "move")}
        labels={workEn}
        onReload={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "This no longer exists. It may have been deleted in another chat.",
    );
    expect(
      screen.queryByRole("button", { name: workEn.retry }),
    ).not.toBeInTheDocument();
  });

  it("a plain failure still offers Try again, so the contrast holds", () => {
    render(
      <NoticeView
        notice={failureNotice(new Error("network"), "move")}
        labels={workSv}
        onReload={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", { name: workSv.retry }),
    ).toBeInTheDocument();
  });

  it("WriteNotice (list controls) shows the text and no retry button", () => {
    const onRetry = vi.fn();
    render(
      <WriteNotice
        failure="not_found"
        labels={manageLabelsSv}
        onReload={vi.fn()}
        onRetry={onRetry}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      manageLabelsSv.notFound,
    );
    expect(
      screen.queryByRole("button", { name: manageLabelsSv.retry }),
    ).not.toBeInTheDocument();
    expect(onRetry).not.toHaveBeenCalled();
  });

  it("WriteNotice has the English text too", () => {
    render(
      <WriteNotice
        failure="not_found"
        labels={manageLabelsEn}
        onReload={vi.fn()}
        onRetry={vi.fn()}
      />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      manageLabelsEn.notFound,
    );
  });

  it("releases the idempotency key so the next attempt is a new write", async () => {
    const { result } = renderHook(() => useWorkWrite());
    const keys: string[] = [];
    await act(async () => {
      await result.current.run("archive:task-1:3", (key) => {
        keys.push(key);
        return Promise.reject(
          Object.assign(new Error("gone"), { code: "not_found" }),
        );
      });
    });
    expect(result.current.failure).toBe("not_found");
    await act(async () => {
      await result.current.run("archive:task-1:3", (key) => {
        keys.push(key);
        return Promise.resolve("ok");
      });
    });
    expect(keys).toHaveLength(2);
    expect(keys[1]).not.toBe(keys[0]);
  });
});

/*
 * The other Work views that write: each shows the text for not_found and no Try again. Where the
 * view holds a list it reads the list again, so the gone row leaves.
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const PROJECT_ID = "019f0000-0000-7000-8000-0000000000c1";

/** A refusal shaped like the host tool error: writeFailure reads `code`. */
function notFoundError(): Error {
  return Object.assign(new Error("Tool request failed"), {
    code: "not_found",
  });
}

function notFoundTransport(overrides: Record<string, unknown>): WorkTransport {
  return overrides as unknown as WorkTransport;
}

describe("not_found in the other Work views", () => {
  it("WorkCard status change shows the text and no Try again", async () => {
    const user = userEvent.setup();
    const frame: WorkCardFrame = {
      kind: "card",
      items: [
        {
          kind: "task",
          id: TASK_ID,
          title: "Ring leverantören",
          status: "todo",
          due_at: null,
          version: 2,
        } satisfies WorkItemRecord,
      ],
      total: 1,
      truncated: false,
    };
    const writer = {
      getTask: vi.fn(),
      updateTask: vi.fn().mockRejectedValue(notFoundError()),
    } as unknown as CardStatusWriter;
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame}
        writer={writer}
      />,
    );

    const group = screen.getByRole("group", {
      name: cardLabelsSv.statusGroup,
    });
    await user.click(
      within(group).getByRole("button", {
        name: cardLabelsSv.taskStatus.completed,
      }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      cardLabelsSv.notFound,
    );
    expect(
      screen.queryByRole("button", { name: cardLabelsSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("TaskSteps checkbox on a removed Step shows the text, reads the list again and drops the row", async () => {
    const user = userEvent.setup();
    const stepA: WorkStep = {
      id: "019f0000-0000-7000-8000-0000000000b1",
      title: "Ring Anna",
      status: "todo",
      due_at: null,
      version: 1,
      position: 0,
    };
    const stepB: WorkStep = {
      ...stepA,
      id: "019f0000-0000-7000-8000-0000000000b2",
      title: "Skriv offert",
      version: 2,
    };
    const listTaskSteps = vi
      .fn()
      .mockResolvedValueOnce({ items: [stepA, stepB], next_cursor: null })
      .mockResolvedValue({ items: [stepB], next_cursor: null });
    const transport = notFoundTransport({
      listTaskSteps,
      completeTaskStep: vi.fn().mockRejectedValue(notFoundError()),
      listStepActions: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
    });
    render(
      <TaskSteps taskId={TASK_ID} transport={transport} labels={workSv} />,
    );

    await user.click(
      await screen.findByRole("checkbox", { name: stepA.title }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(workSv.notFound);
    await waitFor(() =>
      expect(
        screen.queryByRole("checkbox", { name: stepA.title }),
      ).not.toBeInTheDocument(),
    );
    expect(listTaskSteps.mock.calls.length).toBeGreaterThanOrEqual(2);
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText(workSv.stepSaveFailed)).not.toBeInTheDocument();
  });

  it("CreateParentTask for a Project that is gone shows the text and no Try again", async () => {
    const user = userEvent.setup();
    const transport = notFoundTransport({
      createTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <CreateParentTask
        parent={{ project_id: PROJECT_ID }}
        transport={transport}
        labels={workSv}
        onCreated={vi.fn()}
      />,
    );

    await user.click(screen.getByRole("button", { name: workSv.newTask }));
    await user.type(screen.getByLabelText(workSv.newTaskTitle), "Ny uppgift");
    await user.click(screen.getByRole("button", { name: workSv.createTask }));

    expect(await screen.findByRole("alert")).toHaveTextContent(workSv.notFound);
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("ContactsView new Contact refused as not_found shows the text and no Try again", async () => {
    const user = userEvent.setup();
    const frame: WorkContactsFrame = {
      kind: "contacts",
      q: "",
      includeArchived: false,
      page: { items: [], next_cursor: null, q: "", includeArchived: false },
    };
    const transport = notFoundTransport({
      createContact: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <ContactsView
        frame={frame}
        onChange={vi.fn()}
        transport={transport}
        labels={workEn}
        moves={0}
        onOpen={vi.fn()}
      />,
    );

    // The + opens the create field; its text input is named "New contact", and Add creates.
    await user.click(screen.getByRole("button", { name: workEn.newContact }));
    await user.type(
      screen.getByRole("textbox", { name: workEn.newContact }),
      "Anna",
    );
    await user.click(
      screen.getByRole("button", { name: hierarchyDetailLabelsEn.add }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(workEn.notFound);
    expect(
      screen.queryByRole("button", { name: workEn.retry }),
    ).not.toBeInTheDocument();
  });

  it("WorkView Task frame: a status change refused as not_found shows the text and no Try again", async () => {
    const user = userEvent.setup();
    const task: WorkTask = {
      id: TASK_ID,
      title: "Ring leverantören",
      status: "todo",
      due_at: null,
      version: 1,
    };
    const transport = notFoundTransport({
      getTask: vi.fn().mockResolvedValue({ task }),
      listTaskContacts: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listTaskSteps: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listStepActions: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      listTaskExternalReferences: vi
        .fn()
        .mockResolvedValue({ items: [], next_cursor: null }),
      updateTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
      />,
    );

    // The status chip opens the status menu; choosing Blockerad writes it.
    await user.click(
      await screen.findByRole("button", {
        name: new RegExp(`^${hierarchyDetailLabelsSv.changeStatus}: `),
      }),
    );
    await user.click(
      within(screen.getByRole("group", { name: workSv.status })).getByRole(
        "button",
        { name: taskStatusLabel(workSv, "blocked") },
      ),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(workSv.notFound);
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("WorkView inline Task summary: Done refused as not_found shows the text and no Try again", async () => {
    const user = userEvent.setup();
    const task: WorkTask = {
      id: TASK_ID,
      title: "Ring leverantören",
      status: "todo",
      due_at: null,
      version: 1,
    };
    const transport = notFoundTransport({
      updateTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID, task }}
        labels={workSv}
        fullscreen={vi.fn()}
      />,
    );

    await user.click(
      screen.getByRole("button", { name: inlineSummaryLabelsEn.complete }),
    );

    expect(await screen.findByRole("alert")).toHaveTextContent(
      inlineSummaryLabelsEn.notFound,
    );
    expect(
      screen.queryByRole("button", { name: inlineSummaryLabelsEn.retry }),
    ).not.toBeInTheDocument();
  });
});
