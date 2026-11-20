import { fireEvent, render, screen, waitFor } from "@testing-library/react";
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

const ROW = "Väntar på";

describe("TaskWaiting", () => {
  it("reads as one row: the name over since when and the follow-up day, each said once, the follow-up in the overdue tone once it has passed", () => {
    mount(waiting, { contactName: "Anders" });
    const row = screen.getByRole("button", { name: /^Väntar på: Anders/ });
    expect(row).toHaveTextContent("Väntar på");
    expect(row).toHaveTextContent("Anders");
    expect(screen.getAllByText(/sedan 13 nov/)).toHaveLength(1);
    expect(screen.getAllByText(/följ upp igår/)).toHaveLength(1);
    expect(row).toHaveTextContent("sedan 13 nov · följ upp igår");
    expect(screen.getByText("följ upp igår")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    // The panel is closed: no action and no date field is on the screen yet.
    expect(row).toHaveAttribute("aria-expanded", "false");
    expect(screen.queryByRole("button", { name: "Byt person" })).toBeNull();
  });

  it("reads the Contact's name when the record carries only the id", async () => {
    const { getContactContext } = mount(waiting);
    expect(
      await screen.findByRole("button", { name: /^Väntar på: Anders Berg/ }),
    ).toBeInTheDocument();
    expect(getContactContext).toHaveBeenCalledWith(ANDERS);
  });

  it("starts a wait on the Contact found in the search, beginning now", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(idle);
    const row = screen.getByRole("button", { name: "Väntar på: Ingen" });
    expect(row).toHaveTextContent("Ingen");
    await user.click(row);
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
    await user.click(screen.getByRole("button", { name: /^Väntar på: Erik/ }));
    await user.click(screen.getByRole("button", { name: "Byt person" }));
    await user.type(screen.getByRole("searchbox"), "Anders");
    await user.click(
      await screen.findByRole("button", { name: "Anders Berg" }),
    );
    expect(onWrite).toHaveBeenCalledWith({ waiting_on_contact_id: ANDERS });
  });

  it("sets the follow-up day from a shortcut and removes it", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(waiting, { contactName: "Anders" });
    await user.click(
      screen.getByRole("button", { name: /^Väntar på: Anders/ }),
    );
    await user.click(screen.getByRole("button", { name: "Om 3 dagar" }));
    expect(
      dateInputValue(onWrite.mock.calls[0]?.[0].follow_up_at ?? null),
    ).toBe("2026-11-21");

    await user.click(
      screen.getByRole("button", { name: /^Väntar på: Anders/ }),
    );
    await user.click(
      screen.getByRole("button", { name: "Ta bort uppföljning" }),
    );
    expect(onWrite).toHaveBeenLastCalledWith({ follow_up_at: null });
  });

  it("writes the follow-up day when a complete date is chosen, with no Spara button", async () => {
    const user = userEvent.setup();
    const { onWrite } = mount(waiting, { contactName: "Anders" });
    await user.click(
      screen.getByRole("button", { name: /^Väntar på: Anders/ }),
    );
    expect(screen.queryByRole("button", { name: "Spara" })).toBeNull();
    // The field starts on the day it has.
    const day = screen.getByLabelText("Uppföljningsdag");
    expect(day).toHaveValue("2026-11-17");
    // An input event, as the browser sends and as both React and Preact (whose onChange is onInput) take it.
    fireEvent.input(day, { target: { value: "2026-11-30" } });
    expect(onWrite).toHaveBeenCalledTimes(1);
    expect(
      dateInputValue(onWrite.mock.calls[0]?.[0].follow_up_at ?? null),
    ).toBe("2026-11-30");
  });

  it("closes its panel with Escape and returns focus to the row", async () => {
    const user = userEvent.setup();
    mount(waiting, { contactName: "Anders" });
    const row = screen.getByRole("button", { name: /^Väntar på: Anders/ });
    await user.click(row);
    expect(screen.getByRole("group", { name: ROW })).toBeInTheDocument();
    await user.click(screen.getByLabelText("Uppföljningsdag"));
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: ROW })).toBeNull();
    expect(row).toHaveFocus();
    expect(row).toHaveAttribute("aria-expanded", "false");
  });

  it("closes the person search with Escape and returns focus to the row", async () => {
    const user = userEvent.setup();
    mount(idle);
    const row = screen.getByRole("button", { name: "Väntar på: Ingen" });
    await user.click(row);
    expect(screen.getByRole("searchbox")).toHaveFocus();
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("searchbox")).toBeNull();
    expect(row).toHaveFocus();
  });

  it("ends the wait, emptying the person and the follow-up day with it", async () => {
    const { onWrite } = mount(waiting, { contactName: "Anders" });
    const user = userEvent.setup();
    await user.click(
      screen.getByRole("button", { name: /^Väntar på: Anders/ }),
    );
    await user.click(
      screen.getByRole("button", { name: "Jag väntar inte längre" }),
    );
    expect(onWrite).toHaveBeenCalledWith({
      waiting_since: null,
      follow_up_at: null,
      waiting_on_contact_id: null,
    });
  });

  it("only says what it waits on where the host cannot write, and says nothing for a Task that does not wait", () => {
    mount(waiting, { writable: false, contactName: "Anders" });
    expect(screen.getByText("Anders")).toBeInTheDocument();
    expect(screen.getByText(/sedan 13 nov/)).toBeInTheDocument();
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
      screen.getByRole("button", { name: "Waiting on: No one" }),
    );
    await user.type(screen.getByRole("searchbox"), "An");
    await waitFor(() => expect(searchContacts).toHaveBeenCalledWith("An"));
  });
});
