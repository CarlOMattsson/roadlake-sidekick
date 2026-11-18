import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

// Wednesday 18 November 2026, 11:00 on the owner's clock (Europe/Stockholm, UTC+1).
const NOW = new Date("2026-11-18T10:00:00.000Z");
/** 17:30 on the owner's clock on the 18th: a Task Claude made with a time, to be reminded at. */
const AT_1730 = "2026-11-18T16:30:00.000Z";
const BARE_18TH = "2026-11-18T22:59:00.000Z";

const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Hämta paket på ICA",
  status: "todo",
  due_at: AT_1730,
  version: 1,
};

function transport(current: WorkTask) {
  const updateTask = vi.fn((_id: string, version: number, changes: object) =>
    Promise.resolve({ task: { ...current, ...changes, version: version + 1 } }),
  );
  const work = {
    getTask: vi.fn().mockResolvedValue({ task: current }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask,
  } as unknown as WorkTransport;
  return { work, updateTask };
}

function renderTask(work: WorkTransport, labels: WorkLabels = workEn) {
  return render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: task.id }}
      labels={labels}
    />,
  );
}

/** The date chip once the Task has loaded. */
function dueChip(labels: WorkLabels = workEn): Promise<HTMLElement> {
  return screen.findByRole("button", {
    name: new RegExp(`^(${labels.changeDue}|${labels.addDue})`),
  });
}

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

describe("the Task view shows and keeps a due time", () => {
  it("shows the clock time on the date chip, in both languages", async () => {
    const { work } = transport(task);
    const { unmount } = renderTask(work);
    expect(await dueChip()).toHaveTextContent("Wed 18 Nov 5:30 pm");
    unmount();
    renderTask(work, workSv);
    expect(await dueChip(workSv)).toHaveTextContent("ons 18 nov kl 17:30");
  });

  it("shows no time for a date without one", async () => {
    const { work } = transport({ ...task, due_at: BARE_18TH });
    renderTask(work);
    const chip = await dueChip();
    expect(chip).toHaveTextContent("Wed 18 Nov");
    expect(chip).not.toHaveTextContent(/[ap]m/);
  });

  it("Tomorrow keeps the time: 17:30 tomorrow, not the end of the day", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await user.click(await dueChip());
    await user.click(screen.getByRole("button", { name: workEn.dueTomorrow }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-19T16:30:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("Next week keeps the time too", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await user.click(await dueChip());
    await user.click(screen.getByRole("button", { name: workEn.dueNextWeek }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenLastCalledWith(
        task.id,
        1,
        { due_at: "2026-11-23T16:30:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("a day typed in the date field keeps the time, and the field starts on the Task's day", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await user.click(await dueChip());
    await user.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    const date = screen.getByLabelText(workEn.rescheduleDate, {
      selector: "input",
    });
    expect(date).toHaveValue("2026-11-18");
    fireEvent.input(date, { target: { value: "2026-11-25" } });
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-25T16:30:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("the date field of a Task without a date starts on today", async () => {
    const user = userEvent.setup();
    const { work } = transport({ ...task, due_at: null });
    renderTask(work);
    await user.click(await dueChip());
    await user.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    expect(
      screen.getByLabelText(workEn.rescheduleDate, { selector: "input" }),
    ).toHaveValue("2026-11-18");
  });

  it("the time field shows the Task's time and writes a new one when it is left", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await user.click(await dueChip());
    await user.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    expect(screen.getByText(workEn.remindsAtTime)).toBeInTheDocument();
    const time = screen.getByLabelText(workEn.dueTime);
    expect(time).toHaveAttribute("type", "time");
    expect(time).toHaveValue("17:30");
    fireEvent.input(time, { target: { value: "09:15" } });
    // Nothing is written while the time is typed.
    expect(updateTask).not.toHaveBeenCalled();
    fireEvent.blur(time);
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-18T08:15:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("Enter writes the time, and a Task without a date gets the time today", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport({ ...task, due_at: null });
    renderTask(work);
    await user.click(await dueChip());
    await user.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    const time = screen.getByLabelText(workEn.dueTime);
    expect(time).toHaveValue("");
    fireEvent.input(time, { target: { value: "14:00" } });
    fireEvent.keyDown(time, { key: "Enter" });
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-18T13:00:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("Remove time goes back to the end of the same day, and is only offered while there is a time", async () => {
    const user = userEvent.setup();
    const bare = transport({ ...task, due_at: BARE_18TH });
    const { unmount } = renderTask(bare.work);
    await user.click(await dueChip());
    expect(
      screen.queryByRole("button", { name: workEn.removeDueTime }),
    ).toBeNull();
    unmount();

    const { work, updateTask } = transport(task);
    renderTask(work);
    await user.click(await dueChip());
    await user.click(
      screen.getByRole("button", { name: workEn.removeDueTime }),
    );
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: BARE_18TH },
        expect.any(String),
      ),
    );
  });
});

describe("the Task editor has a time field", () => {
  async function openEditor(user: ReturnType<typeof userEvent.setup>) {
    await user.click(
      await screen.findByRole("button", { name: workEn.moreActions }),
    );
    await user.click(screen.getByRole("button", { name: workEn.edit }));
  }

  it("starts on the Task's time, and a new day keeps it", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await openEditor(user);
    expect(screen.getByLabelText(workEn.dueTime)).toHaveValue("17:30");
    expect(screen.getByText(workEn.remindsAtTime)).toBeInTheDocument();
    await user.click(screen.getByRole("button", { name: workEn.dueTomorrow }));
    await user.click(screen.getByRole("button", { name: workEn.save }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-19T16:30:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("sends nothing when neither the day nor the time was touched", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await openEditor(user);
    fireEvent.input(screen.getByLabelText(workEn.titleLabel), {
      target: { value: "Hämta paketet" },
    });
    await user.click(screen.getByRole("button", { name: workEn.save }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { title: "Hämta paketet" },
        expect.any(String),
      ),
    );
  });

  it("saves a changed time on the same day", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await openEditor(user);
    fireEvent.input(screen.getByLabelText(workEn.dueTime), {
      target: { value: "08:00" },
    });
    await user.click(screen.getByRole("button", { name: workEn.save }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: "2026-11-18T07:00:00.000Z" },
        expect.any(String),
      ),
    );
  });

  it("Remove time clears the field and saves the bare date", async () => {
    const user = userEvent.setup();
    const { work, updateTask } = transport(task);
    renderTask(work);
    await openEditor(user);
    await user.click(
      screen.getByRole("button", { name: workEn.removeDueTime }),
    );
    expect(screen.getByLabelText(workEn.dueTime)).toHaveValue("");
    await user.click(screen.getByRole("button", { name: workEn.save }));
    await waitFor(() =>
      expect(updateTask).toHaveBeenCalledWith(
        task.id,
        1,
        { due_at: BARE_18TH },
        expect.any(String),
      ),
    );
  });

  it("offers no time field while there is no date", async () => {
    const user = userEvent.setup();
    const { work } = transport({ ...task, due_at: null });
    renderTask(work);
    await openEditor(user);
    expect(screen.queryByLabelText(workEn.dueTime)).toBeNull();
  });
});
