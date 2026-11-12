import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { ContactCard } from "@/features/work-app/contacts/contact-card";
import { cardLabelsSv } from "@/features/work-app/shared/card-labels";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import { InlineSummary } from "@/features/work-app/inline/inline-summary";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  rootFromToolResult,
  type WorkContactRecord,
  type WorkProject,
  type WorkTask,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

/*
 * A record that is read and no longer exists (the host answers not_found) is not a read error: the view
 * shows one calm line and no Try again, since a retry cannot bring it back. Any other read failure keeps
 * its Try again. A Task or a Project in a framed room names its hidden heading after its own kind.
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const PROJECT_ID = "019f0000-0000-7000-8000-0000000000c1";
const CONTACT_ID = "019f0000-0000-7000-8000-0000000000d1";

/** A refusal shaped like the host tool error: the code is what the views read. */
function notFoundError(): Error {
  return Object.assign(new Error("Tool request failed"), {
    code: "not_found",
  });
}

const task: WorkTask = {
  id: TASK_ID,
  title: "Ring leverantören",
  status: "todo",
  due_at: null,
  version: 1,
};

const project: WorkProject = {
  id: PROJECT_ID,
  title: "Sommarfest",
  status: "active",
  start_date: null,
  target_date: null,
  description: null,
  version: 1,
};

const anna: WorkContactRecord = {
  id: CONTACT_ID,
  display_name: "Anna Andersson",
  email: "anna@example.com",
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 3,
};

/** The transport parts every frame reads when it mounts; the rest is never called. */
function emptyReads() {
  return {
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listProjectTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  };
}

function transportWith(overrides: Record<string, unknown>): WorkTransport {
  return { ...emptyReads(), ...overrides } as unknown as WorkTransport;
}

describe("a record that no longer exists when it is read", () => {
  it("a Task frame read as not_found shows the calm line and no Try again", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
      />,
    );

    expect(
      await screen.findByText("Uppgiften finns inte längre"),
    ).toBeInTheDocument();
    expect(workSv.goneTask).toBe("Uppgiften finns inte längre");
    // The heading already says Uppgift; the eyebrow above it is left out, so the kind word is not repeated.
    expect(screen.queryByText(workSv.task, { selector: "p" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("a Task frame shows the English line in English", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workEn}
      />,
    );

    expect(
      await screen.findByText("This task no longer exists"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: workEn.retry }),
    ).not.toBeInTheDocument();
  });

  it("a Project frame read as not_found shows the calm line and no Try again", async () => {
    const transport = transportWith({
      getProject: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "project", id: PROJECT_ID }}
        labels={workSv}
      />,
    );

    expect(
      await screen.findByText("Projektet finns inte längre"),
    ).toBeInTheDocument();
    expect(screen.queryByText(workSv.project, { selector: "p" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("a Contact frame read as not_found shows the calm line and no Try again", async () => {
    const transport = transportWith({
      getContactContext: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "contact", id: CONTACT_ID }}
        labels={workSv}
      />,
    );

    expect(
      await screen.findByText("Kontakten finns inte längre"),
    ).toBeInTheDocument();
    expect(screen.queryByText(workSv.contact, { selector: "p" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: workSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("the inline Task summary read after fullscreen closes shows the line and no Try again", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
        inlineLabels={inlineSummaryLabelsSv}
        fullscreen={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(inlineSummaryLabelsSv.goneTask),
    ).toBeInTheDocument();
    expect(inlineSummaryLabelsSv.goneTask).toBe("Uppgiften finns inte längre");
    expect(
      screen.queryByRole("button", { name: inlineSummaryLabelsSv.retry }),
    ).not.toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
  });

  it("the inline Contact card whose counts read says not_found shows only the line", async () => {
    const transport = transportWith({
      getContactContext: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <WorkView
        transport={transport}
        initial={rootFromToolResult({ contact: anna })}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    expect(
      await screen.findByText(inlineSummaryLabelsEn.goneContact),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: inlineSummaryLabelsEn.open }),
    ).not.toBeInTheDocument();
  });

  it("the compact Contact card whose read says not_found shows only the line, with no actions", async () => {
    const transport = transportWith({
      getContactContext: vi.fn().mockRejectedValue(notFoundError()),
    });
    render(
      <ContactCard
        contact={anna}
        transport={transport}
        labels={cardLabelsSv}
        onOpen={vi.fn()}
        onEdit={vi.fn()}
      />,
    );

    expect(
      await screen.findByText("Kontakten finns inte längre"),
    ).toBeInTheDocument();
    expect(cardLabelsSv.goneContact).toBe("Kontakten finns inte längre");
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });

  it("a plain read failure still offers Try again, so the contrast holds", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockRejectedValue(new Error("network")),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
      />,
    );

    expect(
      await screen.findByRole("button", { name: workSv.retry }),
    ).toBeInTheDocument();
    expect(screen.queryByText(workSv.goneTask)).not.toBeInTheDocument();
  });

  it("InlineSummary gone state shows the kind and the line, and no action", () => {
    render(
      <InlineSummary
        state="gone"
        labels={inlineSummaryLabelsEn}
        kindLabel={inlineSummaryLabelsEn.kind.project}
        goneKey="goneProject"
      />,
    );
    expect(screen.getByText("Project")).toBeInTheDocument();
    expect(screen.getByRole("status")).toHaveTextContent(
      "This project no longer exists",
    );
    expect(screen.queryByRole("button")).not.toBeInTheDocument();
  });
});

describe("hidden heading of a framed Task or Project", () => {
  it("a Task framed in a room names its hidden heading Uppgift, not Arbete", async () => {
    const transport = transportWith({
      getTask: vi.fn().mockResolvedValue({ task }),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workSv}
        chrome={false}
      />,
    );

    const heading = await screen.findByRole("heading", { level: 1 });
    expect(heading).toHaveTextContent(workSv.task);
    expect(heading).toHaveTextContent("Uppgift");
    expect(heading).not.toHaveTextContent("Arbete");
  });

  it("a Project framed in a room names its hidden heading Projekt, and Project in English", async () => {
    const transport = transportWith({
      getProject: vi.fn().mockResolvedValue({ project }),
    });
    const { unmount } = render(
      <WorkView
        transport={transport}
        initial={{ kind: "project", id: PROJECT_ID }}
        labels={workSv}
        chrome={false}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Projekt" }),
    ).toBeInTheDocument();
    unmount();

    render(
      <WorkView
        transport={transport}
        initial={{ kind: "project", id: PROJECT_ID }}
        labels={workEn}
        chrome={false}
      />,
    );
    expect(
      await screen.findByRole("heading", { level: 1, name: "Project" }),
    ).toBeInTheDocument();
  });
});

describe("the model-context label of a link to a Task", () => {
  it("a Task opened from a Contact's Task list passes its title as the route label", async () => {
    const user = userEvent.setup();
    const onRoute = vi.fn();
    const transport = transportWith({
      getContactContext: vi.fn().mockResolvedValue({
        contact: anna,
        projects: { items: [], next_cursor: null },
        tasks: {
          items: [
            {
              id: TASK_ID,
              title: task.title,
              status: "todo",
              due_at: null,
            },
          ],
          next_cursor: null,
        },
      }),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "contact", id: CONTACT_ID }}
        labels={workEn}
        onRoute={onRoute}
      />,
    );

    await user.click(await screen.findByRole("button", { name: task.title }));

    expect(onRoute).toHaveBeenCalledWith({
      room: "work",
      view: "task",
      id: TASK_ID,
      label: task.title,
    });
  });

  it("a Contact linked from a Task passes the Contact's name as the route label", async () => {
    const user = userEvent.setup();
    const onRoute = vi.fn();
    const transport = transportWith({
      getTask: vi.fn().mockResolvedValue({ task }),
      listTaskContacts: vi.fn().mockResolvedValue({
        items: [{ id: CONTACT_ID, display_name: anna.display_name }],
        next_cursor: null,
      }),
    });
    render(
      <WorkView
        transport={transport}
        initial={{ kind: "task", id: TASK_ID }}
        labels={workEn}
        onRoute={onRoute}
      />,
    );

    await user.click(
      await screen.findByRole("button", { name: anna.display_name }),
    );

    expect(onRoute).toHaveBeenCalledWith({
      room: "contacts",
      view: "contact",
      id: CONTACT_ID,
      label: anna.display_name,
    });
  });
});
