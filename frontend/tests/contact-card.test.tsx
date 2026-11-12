import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardLabelsEn, cardLabelsSv } from "@/features/work-app/card-labels";
import { initialsOf } from "@/features/work-app/contact-card";
import { workEn } from "@/features/work-app/labels";
import { WorkView } from "@/features/work-app/work-view";
import {
  rootFromToolResult,
  type WorkContactRecord,
  type WorkTask,
  type WorkTaskSummary,
  type WorkTransport,
} from "@/features/work-app/transport";

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: "Vill ha offerten före fredag.",
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 3,
};

const linkedTask: WorkTaskSummary = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
};

function contextOf(tasks: WorkTaskSummary[], nextCursor: string | null = null) {
  return Promise.resolve({
    contact: anna,
    projects: { items: [], next_cursor: null },
    tasks: { items: tasks, next_cursor: nextCursor },
  });
}

function transport(
  read: () => Promise<unknown> = () => contextOf([linkedTask, linkedTask]),
) {
  return {
    getContactContext: vi.fn(read),
  } as unknown as WorkTransport & {
    getContactContext: ReturnType<typeof vi.fn>;
  };
}

function compactRoot() {
  return rootFromToolResult({ contact: anna });
}

/** The Contact view's Edit is the first entry of the ⋯ menu: open the menu, then choose Edit. */
async function chooseEdit() {
  await userEvent.click(
    await screen.findByRole("button", { name: workEn.moreActions }),
  );
  await userEvent.click(
    await screen.findByRole("button", { name: workEn.edit }),
  );
}

describe("compact Contact card", () => {
  it("shows the name, the note, the number of connections and two actions", async () => {
    const work = transport();
    const { container } = render(
      <WorkView
        transport={work}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    expect(
      within(card as HTMLElement).getByText(anna.display_name),
    ).toBeVisible();
    expect(
      within(card as HTMLElement).getByText(anna.context_note!),
    ).toHaveClass("work-compact-note");
    expect(
      await screen.findByText(`${cardLabelsEn.connections}: 2`),
    ).toBeInTheDocument();
    expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
    expect(
      within(card as HTMLElement)
        .getAllByRole("button")
        .map((b) => b.textContent),
    ).toEqual([cardLabelsEn.open, cardLabelsEn.edit]);
  });

  it("starts with the kind as a plain eyebrow paragraph, not a heading", () => {
    const { container } = render(
      <WorkView
        transport={transport()}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    const eyebrow = card.firstElementChild;
    expect(eyebrow?.tagName).toBe("P");
    expect(eyebrow).toHaveClass("sk-eyebrow");
    expect(eyebrow).toHaveTextContent(cardLabelsEn.kind.contact);
    expect(within(card as HTMLElement).queryByRole("heading")).toBeNull();
  });

  it("marks the count as at least N when the Tasks continue on another page", async () => {
    const work = transport(() => contextOf([linkedTask], "next"));
    render(
      <WorkView
        transport={work}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    expect(
      await screen.findByText(`${cardLabelsEn.connections}: 1+`),
    ).toBeInTheDocument();
  });

  it("keeps the card and its actions when the count cannot be read", async () => {
    const work = transport(() => Promise.reject(new Error("offline")));
    render(
      <WorkView
        transport={work}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    await waitFor(() => expect(work.getContactContext).toHaveBeenCalled());
    expect(screen.getByText(anna.display_name)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: cardLabelsEn.open }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/^Connections/)).toBeNull();
  });

  it("Open shows the Contact view without its editor", async () => {
    render(
      <WorkView
        transport={transport()}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: cardLabelsEn.open }),
    );
    // The Contact view shows its ⋯ menu; Edit sits inside it, so no editor is open yet.
    expect(
      await screen.findByRole("button", { name: workEn.moreActions }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
    expect(screen.queryByRole("button", { name: workEn.save })).toBeNull();
  });

  it("Edit opens the Contact view with the existing editor shown", async () => {
    const work = transport();
    render(
      <WorkView
        transport={work}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    await userEvent.click(
      screen.getByRole("button", { name: cardLabelsEn.edit }),
    );
    expect(
      await screen.findByRole("button", { name: workEn.save }),
    ).toBeInTheDocument();
    expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  });

  it("uses the Swedish labels for the host's Swedish locale", async () => {
    render(
      <WorkView
        transport={transport()}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsSv}
      />,
    );

    expect(
      screen.getByRole("button", { name: cardLabelsSv.open }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: cardLabelsSv.edit }),
    ).toBeInTheDocument();
    expect(
      await screen.findByText(`${cardLabelsSv.connections}: 2`),
    ).toBeInTheDocument();
  });

  it("shows two initials as hidden text on a circle, with no image", () => {
    const { container } = render(
      <WorkView
        transport={transport()}
        initial={compactRoot()}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    expect(container.querySelector("img")).toBeNull();
    const initials = within(card as HTMLElement).getByText("AA");
    expect(initials).toHaveAttribute("aria-hidden", "true");
    expect(initials.style.borderRadius).toBe("50%");
  });

  it("takes initials from the first and last word, with letters outside ASCII", () => {
    const work = transport();
    const { container } = render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({
          contact: { ...anna, display_name: "  Åsa Öberg " },
        })}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    expect(within(card as HTMLElement).getByText("ÅÖ")).toBeInTheDocument();
  });

  it("leaves a note in parentheses out of the initials: Kerstin Åberg (innebandylaget) is KÅ", () => {
    const work = transport();
    const { container } = render(
      <WorkView
        transport={work}
        initial={rootFromToolResult({
          contact: { ...anna, display_name: "Kerstin Åberg (innebandylaget)" },
        })}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    expect(within(card as HTMLElement).getByText("KÅ")).toBeInTheDocument();
  });

  it("uses the whole name for the initials when the name is only a parenthesis", () => {
    expect(initialsOf("(Kerstin)")).toBe("KE");
    expect(initialsOf("Kerstin Åberg (innebandylaget)")).toBe("KÅ");
  });

  it("uses one word's first two letters as initials for a single name", () => {
    const { container } = render(
      <WorkView
        transport={transport()}
        initial={rootFromToolResult({
          contact: { ...anna, display_name: "Madonna" },
        })}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    const card = container.querySelector("section.work-compact-card")!;
    expect(within(card as HTMLElement).getByText("MA")).toBeInTheDocument();
  });
});

describe("inline Contact frame that carries its context", () => {
  const carried = {
    contact: anna,
    projects: { items: [], next_cursor: null },
    tasks: { items: [linkedTask, linkedTask], next_cursor: null },
  };

  function inline(work: WorkTransport, fullscreen?: () => void) {
    return (
      <WorkView
        transport={work}
        initial={rootFromToolResult(carried)}
        labels={workEn}
        cardLabels={cardLabelsEn}
        fullscreen={fullscreen}
      />
    );
  }

  it("draws the compact summary at once, with no read and no loading text", () => {
    const work = transport();
    const { container } = render(inline(work, vi.fn()));

    expect(screen.queryByText(/Loading|Laddar/)).toBeNull();
    expect(work.getContactContext).not.toHaveBeenCalled();
    expect(container.querySelector("section.work-compact-card")).not.toBeNull();
    expect(screen.getByText(anna.display_name)).toBeVisible();
    expect(screen.getByRole("button", { name: "Open" })).toBeInTheDocument();
    // No editor or Archive inline.
    expect(screen.queryByRole("button", { name: workEn.edit })).toBeNull();
    expect(
      screen.queryByRole("button", { name: /Archive|Arkivera/ }),
    ).toBeNull();
  });

  it("Open asks for fullscreen, and the full view then reads fresh data", async () => {
    const work = transport();
    const fullscreen = vi.fn();
    const { rerender } = render(inline(work, fullscreen));

    await userEvent.click(screen.getByRole("button", { name: "Open" }));
    expect(fullscreen).toHaveBeenCalledTimes(1);
    expect(work.getContactContext).not.toHaveBeenCalled();

    // The host switched to fullscreen: WorkView no longer gets the fullscreen request.
    rerender(inline(work, undefined));
    expect(
      await screen.findByRole("button", { name: workEn.moreActions }),
    ).toBeInTheDocument();
    expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  });

  it("behaves as before when the frame carries no context", async () => {
    const work = transport();
    render(
      <WorkView
        transport={work}
        initial={{ kind: "contact", id: anna.id }}
        labels={workEn}
        cardLabels={cardLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    await chooseEdit();
    expect(work.getContactContext).toHaveBeenCalledWith(anna.id);
  });
});

describe("inline Task frame that carries its record", () => {
  it("draws the summary at once and reads nothing on its own", () => {
    const getTask = vi.fn();
    const task = {
      id: linkedTask.id,
      title: linkedTask.title,
      status: "todo",
      due_at: null,
      version: 1,
    } as unknown as WorkTask;
    render(
      <WorkView
        transport={{ getTask } as unknown as WorkTransport}
        initial={{ kind: "task", id: task.id, task }}
        labels={workEn}
        cardLabels={cardLabelsEn}
        fullscreen={vi.fn()}
      />,
    );

    expect(screen.getByText(linkedTask.title)).toBeVisible();
    // A Task with a version offers "Show more" (the full view), not the old "Open" or a Refresh button.
    expect(
      screen.getByRole("button", { name: "Show more" }),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Refresh" })).toBeNull();
    expect(getTask).not.toHaveBeenCalled();
  });
});

describe("rootFromToolResult keeps the record the result carried", () => {
  const projectRow = {
    id: "019f0000-0000-7000-8000-0000000000b1",
    title: "Offerten till Anna",
    status: "active",
  };
  const contactResult = {
    contact: anna,
    projects: { items: [projectRow], next_cursor: null },
    tasks: { items: [linkedTask], next_cursor: "cursor-2" },
  };

  it("gives a Contact frame the context of a get_contact_context result", () => {
    expect(rootFromToolResult(contactResult)).toEqual({
      kind: "contact",
      id: anna.id,
      context: contactResult,
    });
  });

  it("keeps only the id of a Contact result whose Task row is unreadable", () => {
    const frame = rootFromToolResult({
      ...contactResult,
      tasks: {
        items: [{ id: linkedTask.id, status: "todo", due_at: null }],
        next_cursor: null,
      },
    });
    expect(frame).toEqual({ kind: "contact", id: anna.id });
    expect(frame).not.toHaveProperty("context");
  });

  it("keeps only the id of a Contact result whose aliases are malformed", () => {
    const frame = rootFromToolResult({
      ...contactResult,
      contact: { ...anna, aliases: [{ id: "alias-1" }] },
    });
    expect(frame).toEqual({ kind: "contact", id: anna.id });
    expect(frame).not.toHaveProperty("context");
  });

  it("gives a Contact frame the context of a result exactly as outputSchema describes it", () => {
    // Four profile fields are optional in the schema and left out here; every alias has created_at.
    const wireContact = {
      id: anna.id,
      display_name: anna.display_name,
      email: null,
      phone: null,
      context_note: anna.context_note,
      aliases: [
        {
          id: "019f0000-0000-7000-8000-0000000000d1",
          value: "Annie",
          created_at: "2026-10-24T12:00:00Z",
        },
      ],
      archived: false,
      created_at: "2026-10-24T12:00:00Z",
      updated_at: "2026-10-24T12:00:00Z",
      archived_at: null,
      version: 3,
    };
    const projects = {
      items: [
        {
          id: projectRow.id,
          title: projectRow.title,
          status: "active",
          updated_at: "2026-10-24T12:00:00Z",
          version: 1,
        },
      ],
      next_cursor: null,
    };
    const tasks = {
      items: [
        {
          id: linkedTask.id,
          project_id: null,
          title: linkedTask.title,
          status: "todo",
          priority: "normal",
          due_at: null,
          updated_at: "2026-10-24T12:00:00Z",
          version: 1,
          waiting_on_contact: false,
          waiting_since: null,
          follow_up_at: null,
          follow_up_due: false,
        },
      ],
      next_cursor: "cursor-2",
    };
    const frame = rootFromToolResult({
      contact: wireContact,
      projects,
      tasks,
      journal_entries: { items: [], has_more: false, readable: true },
    });
    expect(frame).toEqual({
      kind: "contact",
      id: anna.id,
      context: {
        contact: {
          ...wireContact,
          relationship: null,
          organization: null,
          role: null,
          address: null,
        },
        projects,
        tasks,
        journal_entries: { items: [], has_more: false, readable: true },
      },
    });
  });

  it("keeps only the id of a Contact result whose profile field has the wrong type", () => {
    const frame = rootFromToolResult({
      ...contactResult,
      contact: { ...anna, relationship: 7 },
    });
    expect(frame).toEqual({ kind: "contact", id: anna.id });
    expect(frame).not.toHaveProperty("context");
  });

  it("keeps the Task of a get_task result", () => {
    const task = {
      id: linkedTask.id,
      title: "Ring Anna om offerten",
      status: "todo",
      due_at: null,
      version: 2,
    };
    expect(rootFromToolResult({ task })).toEqual({
      kind: "task",
      id: task.id,
      task,
    });
  });

  it("keeps only the id of a Task result whose Task is unreadable", () => {
    expect(rootFromToolResult({ task: { id: linkedTask.id } })).toEqual({
      kind: "task",
      id: linkedTask.id,
    });
  });

  it("keeps the Project of a get_project result", () => {
    const project = {
      id: projectRow.id,
      title: projectRow.title,
      status: "active",
      description: null,
      start_date: null,
      target_date: "2026-11-30",
      version: 1,
    };
    expect(rootFromToolResult({ project })).toEqual({
      kind: "project",
      id: project.id,
      project,
    });
  });
});
