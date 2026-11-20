// Where you stand with a Contact, at the top of her card: the wait on her (as a row that opens the Task waited on
// longest), the overdue tone from a week, and the day of the newest linked journal entry. Words in both languages.
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  ContactStanding,
  waitingTasks,
} from "@/features/work-app/contacts/contact-standing";
import {
  contactsRoomLabelsEn,
  contactsRoomLabelsSv,
} from "@/features/work-app/contacts/contacts-room-labels";
import type {
  WorkJournalEntries,
  WorkTaskSummary,
} from "@/features/work-app/transport/transport";

/** A fixed now: the waits below are counted back from this day on the owner calendar. */
const NOW = new Date("2026-11-20T12:00:00Z");

type WaitingTask = WorkTaskSummary & {
  waiting_on_contact?: boolean;
  waiting_since?: string | null;
};

function task(id: string, over: Partial<WaitingTask> = {}): WaitingTask {
  return {
    id: `019f0000-0000-7000-8000-0000000000${id}`,
    title: `Uppgift ${id}`,
    status: "todo",
    due_at: null,
    ...over,
  };
}

/** A Task that waits on the Contact since `daysAgo` days before NOW. */
function waiting(id: string, daysAgo: number, title?: string): WaitingTask {
  const since = new Date(NOW.getTime() - daysAgo * 86_400_000).toISOString();
  return task(id, {
    waiting_on_contact: true,
    waiting_since: since,
    ...(title ? { title } : {}),
  });
}

function journalOf(
  items: { id: string; journal_date: string; title: string }[],
  readable = true,
) {
  return { items, has_more: false, readable } as WorkJournalEntries;
}

const newest = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  journal_date: "2026-11-11",
  title: "Möte om offerten",
};
const older = {
  id: "019f0000-0000-7000-8000-0000000000e2",
  journal_date: "2026-10-28",
  title: "Samtal",
};

function standing(
  props: Partial<Parameters<typeof ContactStanding>[0]> = {},
  dateLocale = "en-GB",
) {
  const onOpen = vi.fn();
  const view = render(
    <ContactStanding
      name="Erik Berg"
      tasks={[]}
      dateLocale={dateLocale}
      onOpen={onOpen}
      now={NOW}
      {...props}
    />,
  );
  return { onOpen, ...view };
}

describe("the wait on a Contact", () => {
  it("says who and for how many days, and opens the Task through onOpen", async () => {
    const user = userEvent.setup();
    const { onOpen } = standing({
      tasks: [waiting("a1", 9, "Offert från Erik")],
    });
    const row = screen.getByRole("button", {
      name: /^You are waiting on Erik for 9 days/,
    });
    // The Task's title stands under the line.
    expect(row).toHaveTextContent("Offert från Erik");
    await user.click(row);
    expect(onOpen).toHaveBeenCalledWith(
      { kind: "task", id: waiting("a1", 9).id },
      "Offert från Erik",
    );
  });

  it("reads the same in Swedish", () => {
    standing(
      { tasks: [waiting("a1", 9, "Offert från Erik"), waiting("a2", 2)] },
      "sv-SE",
    );
    const row = screen.getByRole("button", {
      name: /^Du väntar på Erik sedan 9 dagar/,
    });
    expect(row).toHaveTextContent("Offert från Erik · 1 till");
  });

  it("opens the longest wait of several and counts the others", async () => {
    const user = userEvent.setup();
    const { onOpen } = standing({
      tasks: [
        waiting("a1", 2, "Kort"),
        waiting("a2", 12, "Längst"),
        waiting("a3", 5, "Mitt"),
        task("a4"),
      ],
    });
    const row = screen.getByRole("button");
    expect(row).toHaveTextContent("You are waiting on Erik for 12 days");
    expect(row).toHaveTextContent("Längst · 2 more");
    await user.click(row);
    expect(onOpen).toHaveBeenCalledWith(
      { kind: "task", id: waiting("a2", 12).id },
      "Längst",
    );
  });

  it("says '1 more' for one other wait, and nothing more for a single wait", () => {
    const { unmount } = standing({
      tasks: [waiting("a1", 4, "Första"), waiting("a2", 3, "Andra")],
    });
    expect(screen.getByRole("button")).toHaveTextContent("Första · 1 more");
    unmount();
    standing({ tasks: [waiting("a1", 4, "Första")] });
    expect(screen.getByRole("button")).not.toHaveTextContent("more");
  });

  it("takes the overdue tone from seven days, not before", () => {
    const { unmount } = standing({ tasks: [waiting("a1", 6)] });
    expect(screen.getByRole("button")).not.toHaveAttribute("data-tone");
    unmount();
    const { unmount: second } = standing({ tasks: [waiting("a1", 7)] });
    expect(screen.getByRole("button")).toHaveAttribute("data-tone", "overdue");
    second();
    standing({ tasks: [waiting("a1", 30)] });
    expect(screen.getByRole("button")).toHaveAttribute("data-tone", "overdue");
  });

  it("a wait from today says 'since today', and a wait with no date says no days and has no tone", () => {
    const { unmount } = standing({ tasks: [waiting("a1", 0)] });
    expect(screen.getByRole("button")).toHaveTextContent(
      "You are waiting on Erik since today",
    );
    unmount();
    standing({
      tasks: [task("a2", { waiting_on_contact: true, waiting_since: null })],
    });
    const row = screen.getByRole("button");
    expect(row).toHaveTextContent(/^You are waiting on Erik/);
    expect(row).not.toHaveTextContent("day");
    expect(row).not.toHaveAttribute("data-tone");
  });

  it("shows no row without a Task that waits on her", () => {
    const { container } = standing({
      tasks: [
        task("a1"),
        // waiting_since alone does not make the Task wait on her.
        task("a2", { waiting_since: "2026-11-01T09:00:00Z" }),
        task("a3", { waiting_on_contact: false }),
      ],
    });
    expect(container).toBeEmptyDOMElement();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("puts a wait without a date after the dated ones", () => {
    const undated = task("a1", { waiting_on_contact: true });
    const dated = waiting("a2", 1);
    const order = waitingTasks([undated, dated], NOW).map(
      (entry) => entry.task,
    );
    expect(order).toEqual([dated, undated]);
  });
});

describe("the last journal day", () => {
  it("names the day of the first, newest entry, in English and Swedish", () => {
    const { unmount } = standing({ journal: journalOf([newest, older]) });
    const line = screen.getByText(/^Last in the journal /);
    expect(line.tagName).toBe("TIME");
    expect(line).toHaveAttribute("datetime", "2026-11-11");
    expect(line).toHaveTextContent("Last in the journal 11 Nov");
    expect(screen.queryByText(/28/)).toBeNull();
    unmount();
    standing({ journal: journalOf([newest, older]) }, "sv-SE");
    expect(screen.getByText(/^Senast i dagboken /)).toHaveTextContent(
      "Senast i dagboken 11 nov",
    );
  });

  it("says nothing when the journal cannot be read, has no entry or is not given", () => {
    const { container, unmount } = standing({
      journal: journalOf([newest], false),
    });
    expect(container).toBeEmptyDOMElement();
    unmount();
    const empty = standing({ journal: journalOf([]) });
    expect(empty.container).toBeEmptyDOMElement();
    empty.unmount();
    const none = standing({});
    expect(none.container).toBeEmptyDOMElement();
  });

  it("stands together with the wait, the wait first", () => {
    const { container } = standing({
      tasks: [waiting("a1", 9, "Offert")],
      journal: journalOf([newest]),
    });
    const block = container.querySelector(".work-contact-standing");
    expect(block?.children).toHaveLength(2);
    expect(block?.children[0]).toHaveClass("work-contact-waiting");
    expect(block?.children[1]).toHaveClass("work-contact-last");
  });
});

describe("the words", () => {
  it("are the same in both languages for a wait of one day and of none", () => {
    expect(contactsRoomLabelsEn.waitingOn("Erik", 1)).toBe(
      "You are waiting on Erik for 1 day",
    );
    expect(contactsRoomLabelsSv.waitingOn("Erik", 1)).toBe(
      "Du väntar på Erik sedan 1 dag",
    );
    expect(contactsRoomLabelsEn.waitingOn("Erik", 0)).toBe(
      "You are waiting on Erik since today",
    );
    expect(contactsRoomLabelsSv.waitingOn("Erik", 0)).toBe(
      "Du väntar på Erik sedan idag",
    );
    expect(contactsRoomLabelsEn.waitingOn("Erik", null)).toBe(
      "You are waiting on Erik",
    );
    expect(contactsRoomLabelsSv.waitingTask("Offert", 2)).toBe(
      "Offert · 2 till",
    );
    expect(contactsRoomLabelsEn.waitingTask("Offert", 0)).toBe("Offert");
  });
});
