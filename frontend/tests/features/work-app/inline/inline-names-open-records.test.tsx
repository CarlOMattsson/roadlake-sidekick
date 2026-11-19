import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { WorkView } from "@/features/work-app/view/work-view";
import { workEn } from "@/features/work-app/shared/labels";
import {
  AgendaSummary,
  ContactsSummary,
} from "@/features/work-app/inline/inline-summary";
import { inlineSummaryLabelsEn } from "@/features/work-app/inline/inline-summary-labels";
import type {
  WorkFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// A contact or project name in an inline card opens its record in the full view, as an agenda row opens its Task.
const erik = "019f0000-0000-7000-8000-0000000000c1";
const waitingOnErik: WorkItemRecord = {
  kind: "task",
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Svar om bildformat",
  status: "todo",
  version: 1,
  agenda_group: "upcoming",
  waiting: true,
  waiting_since: "2026-10-18T09:00:00+02:00",
  waiting_on_contact_id: erik,
  waiting_on_contact_name: "Erik Holm",
};
const waitingOnNobody: WorkItemRecord = {
  ...waitingOnErik,
  id: "019f0000-0000-7000-8000-0000000000a2",
  title: "Svar från banken",
  waiting_on_contact_id: null,
  waiting_on_contact_name: null,
};
const page = { items: [waitingOnErik, waitingOnNobody], next_cursor: null };

describe("the inline waiting view", () => {
  it("opens the Contact from the name and the Task from its title", async () => {
    const user = userEvent.setup();
    const onOpenContact = vi.fn();
    const onOpenItem = vi.fn();
    render(
      <AgendaSummary
        page={page}
        filters={{ waiting: "waiting" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
        onOpenItem={onOpenItem}
        onOpenContact={onOpenContact}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Erik Holm" }));
    expect(onOpenContact).toHaveBeenCalledWith({ id: erik, name: "Erik Holm" });
    await user.click(screen.getByRole("button", { name: waitingOnErik.title }));
    expect(onOpenItem).toHaveBeenCalledWith(waitingOnErik);
    // A wait that names nobody has no name to press; its Task still opens.
    expect(screen.getByText("Someone").tagName).toBe("SPAN");
    expect(
      screen.getByRole("button", { name: waitingOnNobody.title }),
    ).toBeInTheDocument();
  });

  it("is text only without a way to open", () => {
    render(
      <AgendaSummary
        page={page}
        filters={{ waiting: "waiting" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Erik Holm" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: waitingOnErik.title }),
    ).toBeNull();
  });
});

describe("the inline Contact list", () => {
  const contacts = [
    { id: "c1", name: "Anna Lind" },
    { id: "c2", name: "Bo Berg" },
  ];

  it("opens a Contact from its row", async () => {
    const user = userEvent.setup();
    const onOpenContact = vi.fn();
    render(
      <ContactsSummary
        count={2}
        more={false}
        contacts={contacts}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
        onOpenContact={onOpenContact}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Bo Berg" }));
    expect(onOpenContact).toHaveBeenCalledWith(contacts[1]);
  });

  it("draws plain names, nothing that looks pressable, without a way to open", () => {
    render(
      <ContactsSummary
        count={2}
        more={false}
        contacts={contacts}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByRole("button", { name: "Bo Berg" })).toBeNull();
    expect(screen.getByText("Bo Berg")).toBeInTheDocument();
  });
});

describe("WorkView inline cards ask for the Contact as the target of the full view", () => {
  /** The Contact frame the press opens reads its context; it is left pending, the test is about what is asked of the host. */
  function workWith(): WorkTransport {
    return {
      getContactContext: vi.fn().mockReturnValue(new Promise(() => undefined)),
      listContacts: vi.fn().mockResolvedValue({
        items: [{ id: "c1", display_name: "Anna Lind" }],
        next_cursor: null,
      }),
    } as unknown as WorkTransport;
  }

  it("from a waiting row", async () => {
    const user = userEvent.setup();
    const fullscreen = vi.fn();
    const openRecord = vi.fn();
    const root: WorkFrame = {
      kind: "agenda",
      filters: { waiting: "waiting" },
      page,
    };
    render(
      <WorkView
        transport={workWith()}
        initial={root}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={fullscreen}
        openRecord={openRecord}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Erik Holm" }));
    expect(openRecord).toHaveBeenCalledWith({
      room: "contacts",
      view: "contact",
      id: erik,
      label: "Erik Holm",
    });
    expect(fullscreen).not.toHaveBeenCalled();
  });

  it("from a row of the Contact list", async () => {
    const user = userEvent.setup();
    const openRecord = vi.fn();
    render(
      <WorkView
        transport={workWith()}
        initial={{ kind: "contacts", q: "", includeArchived: false }}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
        openRecord={openRecord}
      />,
    );
    await user.click(await screen.findByRole("button", { name: "Anna Lind" }));
    expect(openRecord).toHaveBeenCalledWith({
      room: "contacts",
      view: "contact",
      id: "c1",
      label: "Anna Lind",
    });
  });

  it("and offers no name to press where fullscreen has no way to carry it", async () => {
    render(
      <WorkView
        transport={workWith()}
        initial={{ kind: "contacts", q: "", includeArchived: false }}
        labels={workEn}
        inlineLabels={inlineSummaryLabelsEn}
        fullscreen={vi.fn()}
      />,
    );
    expect(await screen.findByText("Anna Lind")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Anna Lind" })).toBeNull();
  });
});
