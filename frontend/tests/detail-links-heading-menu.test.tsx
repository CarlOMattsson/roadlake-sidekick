import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { openLinkedRowMenu } from "./linked-row-menu-helpers";
import { linksLabelsEn } from "@/features/work-app/shared/links-labels";
import { ContactWays } from "@/features/work-app/contacts/contact-card";
import { hierarchyDetailLabelsEn } from "@/features/work-app/hierarchy/hierarchy-detail-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  manageLabelsEn,
  manageLabelsSv,
} from "@/features/work-app/shared/manage-labels";
import type {
  WorkContactRecord,
  WorkProjectSummary,
  WorkTask,
  WorkTaskSummary,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

/** A Task's or Contact's link is removed from the ⋯ of the heading row, and Undo writes it back. */

const KEY =
  /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/;

const taskA: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const taskB: WorkTaskSummary = {
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Skicka faktura",
  status: "doing",
  due_at: null,
};
const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: "anna@example.test",
  phone: "+46 70 000 00 01",
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};
const projectA: WorkProjectSummary = {
  id: "019f0000-0000-7000-8000-0000000000d1",
  title: "Offert till Anna",
  status: "active",
};

/** The Task's read and writes, plus the Contact context and the Contact-to-Project links. */
function transport(overrides: Partial<WorkTransport> = {}): WorkTransport {
  return {
    getTask: vi.fn().mockResolvedValue({ task: taskA }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [anna], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask: vi.fn().mockResolvedValue({ task: { ...taskA, version: 2 } }),
    linkContactToTask: vi.fn().mockResolvedValue({ linked: true }),
    unlinkContactFromTask: vi.fn().mockResolvedValue({ linked: false }),
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: { items: [projectA], next_cursor: null },
      tasks: { items: [taskB], next_cursor: null },
    }),
    linkContactToProject: vi.fn().mockResolvedValue({ linked: true }),
    unlinkContactFromProject: vi.fn().mockResolvedValue({ linked: false }),
    ...overrides,
  } as unknown as WorkTransport;
}

/** The ⋯ buttons that sit inside a list row (none may exist there). */
function moreButtonsInRows() {
  return screen
    .queryAllByRole("button", { name: /Fler alternativ|More options/u })
    .filter(
      (button) =>
        button.closest("li") !== null &&
        !button.classList.contains("work-visually-hidden"),
    );
}

describe("Task view: the Contact row's own menu removes its link, and Undo writes it back", () => {
  it("keeps the row with 'Link removed' and Undo, and Undo sends link_contact_to_task", async () => {
    const user = userEvent.setup();
    const unlink = vi.fn().mockResolvedValue({ linked: false });
    const link = vi.fn().mockResolvedValue({ linked: true });
    const work = transport({
      unlinkContactFromTask: unlink,
      linkContactToTask: link,
    });
    render(
      <WorkView
        transport={work}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
      />,
    );
    const row = (
      await screen.findByRole("button", { name: anna.display_name })
    ).closest("li") as HTMLElement;
    await user.click(await openLinkedRowMenu(row));
    // The task's ⋯ no longer carries an entry per link.
    expect(screen.queryByText(/Remove link to/)).toBeNull();
    expect(await within(row).findByRole("status")).toHaveTextContent(
      linksLabelsEn.linkRemoved,
    );
    expect(unlink).toHaveBeenCalledTimes(1);
    expect(unlink).toHaveBeenCalledWith(
      taskA.id,
      anna.id,
      expect.stringMatching(KEY),
    );

    await user.click(
      within(row).getByRole("button", { name: workEn.agendaUndo }),
    );
    await waitFor(() => expect(link).toHaveBeenCalledTimes(1));
    expect(link).toHaveBeenCalledWith(
      taskA.id,
      anna.id,
      expect.stringMatching(KEY),
    );
    await waitFor(() => expect(within(row).queryByRole("status")).toBeNull());
    expect(
      within(row).getByRole("button", { name: anna.display_name }),
    ).toBeInTheDocument();
  });

  it("names the remove-link entry and the hidden menu button in Swedish for a Swedish host", async () => {
    const user = userEvent.setup();
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "task", id: taskA.id }}
        labels={workSv}
      />,
    );
    const row = (
      await screen.findByRole("button", { name: anna.display_name })
    ).closest("li") as HTMLElement;
    // The hidden button stands last in the row, named after the Contact; it opens the menu and focuses its entry.
    await user.click(
      within(row).getByRole("button", {
        name: workSv.rowMenuButton(anna.display_name),
      }),
    );
    expect(
      within(row).getByRole("button", { name: manageLabelsSv.removeLink }),
    ).toHaveFocus();
  });

  it("opens with Shift+F10, closes with Escape back on the row, and keeps the heading ⋯ free of link entries", async () => {
    const user = userEvent.setup();
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
      />,
    );
    const title = await screen.findByRole("button", {
      name: anna.display_name,
    });
    const row = title.closest("li") as HTMLElement;
    expect(
      within(row).queryByRole("button", { name: /Remove link/ }),
    ).toBeNull();
    title.focus();
    await user.keyboard("{Shift>}{F10}{/Shift}");
    const remove = await within(row).findByRole("button", {
      name: manageLabelsEn.removeLink,
    });
    expect(remove).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      within(row).queryByRole("button", { name: /Remove link/ }),
    ).toBeNull();
    expect(title).toHaveFocus();
    await user.click(screen.getByRole("button", { name: workEn.moreActions }));
    expect(screen.getByRole("button", { name: workEn.edit })).toBeVisible();
    expect(screen.queryByText(/Remove link to/)).toBeNull();
  });

  it("puts the focus on Undo after the removal", async () => {
    const user = userEvent.setup();
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
      />,
    );
    const row = (
      await screen.findByRole("button", { name: anna.display_name })
    ).closest("li") as HTMLElement;
    await user.click(await openLinkedRowMenu(row));
    expect(
      await within(row).findByRole("button", { name: workEn.agendaUndo }),
    ).toHaveFocus();
  });
});

describe("Contact view: the Project row's own menu removes its link, and Undo writes it back", () => {
  it("keeps the Project row with Undo, and Undo sends link_contact_to_project", async () => {
    const user = userEvent.setup();
    const unlink = vi.fn().mockResolvedValue({ linked: false });
    const link = vi.fn().mockResolvedValue({ linked: true });
    const work = transport({
      unlinkContactFromProject: unlink,
      linkContactToProject: link,
    });
    render(
      <WorkView
        transport={work}
        initial={{ kind: "contact", id: anna.id }}
        labels={workEn}
      />,
    );
    const row = (
      await screen.findByRole("button", { name: projectA.title })
    ).closest("li") as HTMLElement;
    await user.click(await openLinkedRowMenu(row));
    expect(await within(row).findByRole("status")).toHaveTextContent(
      linksLabelsEn.linkRemoved,
    );
    expect(unlink).toHaveBeenCalledTimes(1);
    expect(unlink).toHaveBeenCalledWith(
      anna.id,
      projectA.id,
      expect.stringMatching(KEY),
    );

    await user.click(
      within(row).getByRole("button", { name: workEn.agendaUndo }),
    );
    await waitFor(() => expect(link).toHaveBeenCalledTimes(1));
    expect(link).toHaveBeenCalledWith(
      anna.id,
      projectA.id,
      expect.stringMatching(KEY),
    );
  });
});

describe("no more-menu inside a list row", () => {
  it("draws no ⋯ in the Task view's Contact rows, only on the heading row", async () => {
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "task", id: taskA.id }}
        labels={workEn}
      />,
    );
    await screen.findByRole("button", { name: anna.display_name });
    expect(
      screen.getByRole("button", { name: workEn.moreActions }).closest("li"),
    ).toBeNull();
    expect(moreButtonsInRows()).toHaveLength(0);
  });

  it("draws no ⋯ in the Contact view's Task and Project rows, only on the heading row", async () => {
    render(
      <WorkView
        transport={transport()}
        initial={{ kind: "contact", id: anna.id }}
        labels={workEn}
      />,
    );
    await screen.findByRole("button", { name: taskB.title });
    await screen.findByRole("button", { name: projectA.title });
    expect(
      screen.getByRole("button", { name: workEn.moreActions }).closest("li"),
    ).toBeNull();
    expect(moreButtonsInRows()).toHaveLength(0);
  });
});

describe("ContactWays", () => {
  it("hands a mailto: link to onOpenLink instead of following it", async () => {
    const user = userEvent.setup();
    const onOpenLink = vi.fn();
    render(
      <ContactWays
        contact={anna}
        labels={hierarchyDetailLabelsEn}
        onOpenLink={onOpenLink}
      />,
    );
    await user.click(
      screen.getByRole("button", {
        name: new RegExp(`^${hierarchyDetailLabelsEn.waysToReach}`),
      }),
    );
    const mail = screen.getByRole("link", { name: anna.email as string });
    expect(mail).toHaveAttribute("href", `mailto:${anna.email}`);
    await user.click(mail);
    expect(onOpenLink).toHaveBeenCalledTimes(1);
    expect(onOpenLink).toHaveBeenCalledWith(`mailto:${anna.email}`);
  });
});
