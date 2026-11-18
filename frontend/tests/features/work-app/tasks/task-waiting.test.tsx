import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { TaskWaiting } from "@/features/work-app/tasks/task-waiting";
import { dateInputValue } from "@/features/work-app/tasks/task-edit";
import type {
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/** 18 Nov 2026, 12:00 UTC (13:00 in Stockholm). */
const NOW = new Date("2026-11-18T12:00:00Z");
const ANDERS = "019f0000-0000-7000-8000-0000000000a9";

const idle: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Svar från Anders om bildformat",
  status: "todo",
  due_at: null,
  version: 3,
};
const waiting: WorkTask = {
  ...idle,
  waiting_since: "2026-11-13T09:00:00+01:00",
  follow_up_at: "2026-11-17T09:00:00+01:00",
  waiting_on_contact_id: ANDERS,
};

function fakeTransport() {
  const searchContacts = vi.fn().mockResolvedValue({
    items: [{ id: ANDERS, display_name: "Anders Berg" }],
    next_cursor: null,
  });
  const getContactContext = vi.fn().mockResolvedValue({
    contact: { id: ANDERS, display_name: "Anders Berg" },
  });
  return {
    transport: {
      searchContacts,
      getContactContext,
    } as unknown as WorkTransport,
    searchContacts,
    getContactContext,
  };
}

function mount(
  task: WorkTask,
  options: {
    writable?: boolean;
    contactName?: string | null;
    labels?: typeof workSv;
  } = {},
) {
  const fake = fakeTransport();
  const onWrite = vi.fn<(changes: WorkTaskChanges) => void>();
  render(
    <TaskWaiting
      task={task}
      labels={options.labels ?? workSv}
      transport={fake.transport}
      contactName={options.contactName}
      writable={options.writable ?? true}
      busy={false}
      now={NOW}
      onWrite={onWrite}
    />,
  );
  return { ...fake, onWrite };
}

describe("TaskWaiting", () => {
  it("says who the Task waits on, since when and the follow-up day, the day in the overdue tone once it has passed", () => {
    mount(waiting, { contactName: "Anders" });
    expect(
      screen.getByText("Väntar på Anders sedan 13 nov"),
    ).toBeInTheDocument();
    expect(screen.getByText("följ upp igår")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
  });

  it("reads the Contact's name when the record carries only the id", async () => {
    const { getContactContext } = mount(waiting);
    expect(
      await screen.findByText("Väntar på Anders Berg sedan 13 nov"),
    ).toBeInTheDocument();
    expect(getContactContext).toHaveBeenCalledWith(ANDERS);
  });

  it("starts a wait on the Contact found in the search, beginning now", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(idle);
    await user.click(
      screen.getByRole("button", { name: "Jag väntar på någon" }),
    );
    await user.type(screen.getByRole("searchbox"), "Anders");
    await user.click(
      await screen.findByRole("button", { name: "Anders Berg" }),
    );
    expect(onWrite).toHaveBeenCalledWith({
      waiting_on_contact_id: ANDERS,
      waiting_since: NOW.toISOString(),
    });
  });

  it("changes the person without touching when the wait began", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(waiting, { contactName: "Erik" });
    await user.click(screen.getByRole("button", { name: "Byt person" }));
    await user.type(screen.getByRole("searchbox"), "Anders");
    await user.click(
      await screen.findByRole("button", { name: "Anders Berg" }),
    );
    expect(onWrite).toHaveBeenCalledWith({ waiting_on_contact_id: ANDERS });
  });

  it("sets the follow-up day from a shortcut and from the date field, and removes it", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(waiting, { contactName: "Anders" });
    await user.click(screen.getByRole("button", { name: /Följ upp: igår/ }));
    await user.click(screen.getByRole("button", { name: "Om 3 dagar" }));
    expect(
      dateInputValue(onWrite.mock.calls[0]?.[0].follow_up_at ?? null),
    ).toBe("2026-11-21");

    await user.click(screen.getByRole("button", { name: /Följ upp: igår/ }));
    // The field starts on the day it has, so Spara alone changes nothing wrong.
    const day = screen.getByLabelText("Uppföljningsdag");
    expect(day).toHaveValue("2026-11-17");
    await user.clear(day);
    await user.type(day, "2026-11-30");
    await user.click(screen.getByRole("button", { name: "Spara" }));
    expect(
      dateInputValue(onWrite.mock.calls[1]?.[0].follow_up_at ?? null),
    ).toBe("2026-11-30");

    await user.click(screen.getByRole("button", { name: /Följ upp: igår/ }));
    await user.click(
      screen.getByRole("button", { name: "Ta bort uppföljning" }),
    );
    expect(onWrite).toHaveBeenLastCalledWith({ follow_up_at: null });
  });

  it("ends the wait, emptying the person and the follow-up day with it", async () => {
    const { onWrite } = mount(waiting, { contactName: "Anders" });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Jag väntar inte längre" }));
    expect(onWrite).toHaveBeenCalledWith({
      waiting_since: null,
      follow_up_at: null,
      waiting_on_contact_id: null,
    });
  });

  it("only says what it waits on where the host cannot write, and says nothing for a Task that does not wait", () => {
    mount(waiting, { writable: false, contactName: "Anders" });
    expect(
      screen.getByText("Väntar på Anders sedan 13 nov"),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows nothing for a Task that does not wait and cannot be written, or that is done", () => {
    const { container } = render(
      <TaskWaiting
        task={idle}
        labels={workEn}
        transport={fakeTransport().transport}
        writable={false}
        busy={false}
        now={NOW}
        onWrite={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    const done = render(
      <TaskWaiting
        task={{ ...waiting, status: "completed" }}
        labels={workEn}
        transport={fakeTransport().transport}
        writable
        busy={false}
        now={NOW}
        onWrite={vi.fn()}
      />,
    );
    expect(done.container).toBeEmptyDOMElement();
  });

  it("offers the same controls in English", async () => {
    const { searchContacts } = mount(idle, { labels: workEn });
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: "I’m waiting on someone" }),
    );
    await user.type(screen.getByRole("searchbox"), "An");
    await waitFor(() => expect(searchContacts).toHaveBeenCalledWith("An"));
  });
});
