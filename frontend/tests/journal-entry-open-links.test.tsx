import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalFrame,
  JournalTransport,
} from "@/features/journal-app/transport";

// The entry view in the room: a contact chip opens its contact, and the saved entry opens its created tasks.
// Without the handlers (no cross links, plain host) the chips and the notice carry no buttons.
const entryId = "019f0000-0000-7000-8000-0000000000e1";
const contactAnna = "019f0000-0000-7000-8000-0000000000c1";
const contactNoName = "019f0000-0000-7000-8000-0000000000c2";
const projectOffer = "019f0000-0000-7000-8000-0000000000p1";
const taskIds = [
  "019f0000-0000-7000-8000-0000000000t1",
  "019f0000-0000-7000-8000-0000000000t2",
  "019f0000-0000-7000-8000-0000000000t3",
  "019f0000-0000-7000-8000-0000000000t4",
];

const entry: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: null,
  key_points: [],
  project_ids: [projectOffer],
  task_ids: [],
  contact_ids: [contactAnna, contactNoName],
  links: [
    { kind: "project", id: projectOffer, label: "Offert Norr" },
    { kind: "contact", id: contactAnna, label: "Anna Berg" },
    { kind: "contact", id: contactNoName, label: null },
  ],
  tags: [],
  archived: false,
  version: 2,
};

/** A transport that answers only the entry read; nothing else is used by the entry view. */
function transportFor(): JournalTransport {
  const unused = () => Promise.reject(new Error("not used in this test"));
  return {
    getDay: unused,
    getEntry: () => Promise.resolve({ entry }),
    getSource: unused,
    getDraft: unused,
    updateDraft: unused,
    rejectDraft: unused,
    finalizeDraft: unused,
  };
}

function renderEntry(props: {
  initial?: JournalFrame;
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  onOpenTask?: (id: string) => void;
}) {
  const initial: JournalFrame = props.initial ?? { kind: "entry", id: entryId };
  render(
    <JournalView
      transport={transportFor()}
      initial={initial}
      labels={journalEn}
      onOpenContact={props.onOpenContact}
      onOpenTask={props.onOpenTask}
    />,
  );
  return screen.findByRole("heading", { level: 2, name: entry.title });
}

describe("journal entry view: contact chips", () => {
  it("draws a contact chip as a button named by the contact and opens it with the id and label", async () => {
    const onOpenContact = vi.fn();
    await renderEntry({ onOpenContact });
    const user = userEvent.setup();

    const chip = screen.getByRole("button", { name: "Anna Berg" });
    expect(chip).toHaveClass("journal-chip-name");
    expect(chip.closest("li")).toHaveClass("journal-chip");

    await user.click(chip);
    expect(onOpenContact).toHaveBeenCalledTimes(1);
    expect(onOpenContact).toHaveBeenCalledWith({
      id: contactAnna,
      label: "Anna Berg",
    });
  });

  it("passes a null label for a contact without a name, and the button keeps the contact fallback name", async () => {
    const onOpenContact = vi.fn();
    await renderEntry({ onOpenContact });
    const user = userEvent.setup();

    await user.click(screen.getByRole("button", { name: "Contact" }));
    expect(onOpenContact).toHaveBeenCalledWith({
      id: contactNoName,
      label: null,
    });
  });

  it("keeps a project chip a plain span even when a contact handler exists", async () => {
    await renderEntry({ onOpenContact: vi.fn() });

    const project = screen.getByText("Offert Norr");
    expect(project.tagName).toBe("SPAN");
    expect(project).toHaveClass("journal-chip-name");
    expect(
      screen.queryByRole("button", { name: "Offert Norr" }),
    ).not.toBeInTheDocument();
  });

  it("draws the contact chip as a plain span when no contact handler is passed", async () => {
    await renderEntry({});

    const contact = screen.getByText("Anna Berg");
    expect(contact.tagName).toBe("SPAN");
    expect(contact).toHaveClass("journal-chip-name");
    expect(
      screen.queryByRole("button", { name: "Anna Berg" }),
    ).not.toBeInTheDocument();
  });
});

describe("journal entry view: tasks created by a saved draft", () => {
  const saved: JournalFrame = {
    kind: "entry",
    id: entryId,
    notice: { created: taskIds.length, updated: 0, createdTaskIds: taskIds },
  };

  it("offers one Open task button per created task, at most three", async () => {
    await renderEntry({ initial: saved, onOpenTask: vi.fn() });

    const buttons = screen.getAllByRole("button", { name: "Open task" });
    expect(buttons).toHaveLength(3);
  });

  it("opens the task whose button was pressed", async () => {
    const onOpenTask = vi.fn();
    await renderEntry({ initial: saved, onOpenTask });
    const user = userEvent.setup();

    const second = screen.getAllByRole("button", { name: "Open task" })[1];
    await user.click(second as HTMLElement);
    expect(onOpenTask).toHaveBeenCalledTimes(1);
    expect(onOpenTask).toHaveBeenCalledWith(taskIds[1]);
  });

  it("shows no task buttons when no task handler is passed", async () => {
    await renderEntry({ initial: saved });

    expect(
      screen.queryByRole("button", { name: "Open task" }),
    ).not.toBeInTheDocument();
    // The saved notice itself still shows, as before.
    expect(screen.getByRole("status")).toHaveTextContent(
      "Journal entry saved. 4 tasks created, 0 updated.",
    );
  });
});
