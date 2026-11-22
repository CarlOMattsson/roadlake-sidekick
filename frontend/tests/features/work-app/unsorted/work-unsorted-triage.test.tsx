import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { placeChanges } from "@/features/work-app/hierarchy/group-choices";
import { workSv } from "@/features/work-app/shared/labels";
import { taskPlaceLabelsSv } from "@/features/work-app/tasks/task-place-labels";
import type {
  WorkDomain,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { UnsortedView } from "@/features/work-app/unsorted/unsorted-view";

// Simulated host (a fake transport), not a test in a real Claude or Android host.

const taskA: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  title: "Köp ny dammsugare",
  status: "todo",
  due_at: null,
  version: 3,
  domain_id: null,
};
const taskB: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000c2",
  title: "Ring försäkringsbolaget",
  status: "todo",
  due_at: null,
  version: 1,
  domain_id: null,
};
const HOME = "019f0000-0000-7000-8000-0000000000d1";
const WORK = "019f0000-0000-7000-8000-0000000000d2";
const domains: WorkDomain[] = [
  { id: HOME, name: "Hem", accent: "teal" },
  { id: WORK, name: "Jobb", accent: "blue" },
];

function makeTransport() {
  const updateTask = vi.fn(
    (id: string, version: number, changes: WorkTaskChanges) =>
      Promise.resolve({
        task: {
          id,
          title: "",
          status: "todo",
          due_at: null,
          version: version + 1,
          domain_id: changes.domain_id ?? null,
        },
      }),
  );
  const transport = {
    listUnsortedTasks: vi.fn().mockResolvedValue({
      items: [taskA, taskB],
      next_cursor: null,
    }),
    listDomains: vi.fn().mockResolvedValue(domains),
    getWorkHierarchy: vi.fn().mockResolvedValue({
      kind: "hierarchy",
      truncated: false,
      nodes: [{ kind: "domain", id: HOME, title: "Hem", parent_id: null }],
    }),
    updateTask,
  } as unknown as WorkTransport;
  return { transport, updateTask };
}

/** The title button of a row, once the rows have been read. */
const titleOf = (title: string) =>
  screen.findByRole("button", { name: title, description: "" });

describe("UnsortedView as a triage list (onOpen given)", () => {
  it("opens the Task from its title", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    render(
      <UnsortedView
        transport={makeTransport().transport}
        labels={workSv}
        onOpen={onOpen}
      />,
    );

    await user.click(await titleOf(taskA.title));

    expect(onOpen).toHaveBeenCalledWith(
      expect.objectContaining({ id: taskA.id }),
    );
    const list = document.querySelector("ul[data-triage]");
    expect(list).not.toBeNull();
    expect(list?.querySelectorAll("li[data-sk-row]")).toHaveLength(2);
  });

  it("sorts into the second Domain on the key 2, tells onSorted, and moves focus to the next row's title", async () => {
    const user = userEvent.setup();
    const onSorted = vi.fn();
    const { transport, updateTask } = makeTransport();
    render(
      <UnsortedView
        transport={transport}
        labels={workSv}
        onOpen={vi.fn()}
        onSorted={onSorted}
      />,
    );
    const first = await titleOf(taskA.title);
    // The Domain buttons carry the keys, so they are offered once the Domains have been read.
    await screen.findByRole("group", {
      name: workSv.unsortedRowFor(taskA.title),
    });
    first.focus();

    await user.keyboard("2");

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    const [id, version, changes] = updateTask.mock.calls[0]!;
    expect(id).toBe(taskA.id);
    expect(version).toBe(3);
    expect(changes).toEqual(placeChanges({ kind: "domain", id: WORK }));
    await waitFor(() => expect(onSorted).toHaveBeenCalledTimes(1));
    await waitFor(() =>
      expect(screen.getByRole("button", { name: taskB.title })).toHaveFocus(),
    );
  });

  it("sorts on a key pressed in a Domain button of the row too", async () => {
    const user = userEvent.setup();
    const { transport, updateTask } = makeTransport();
    render(
      <UnsortedView transport={transport} labels={workSv} onOpen={vi.fn()} />,
    );
    const group = await screen.findByRole("group", {
      name: workSv.unsortedRowFor(taskB.title),
    });
    within(group).getByRole("button", { name: "Hem" }).focus();

    await user.keyboard("1");

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]![0]).toBe(taskB.id);
    expect(updateTask.mock.calls[0]![2]).toEqual(
      placeChanges({ kind: "domain", id: HOME }),
    );
  });

  it("does nothing for a number with no Domain of that place", async () => {
    const user = userEvent.setup();
    const { transport, updateTask } = makeTransport();
    render(
      <UnsortedView transport={transport} labels={workSv} onOpen={vi.fn()} />,
    );
    (await titleOf(taskA.title)).focus();
    await screen.findByRole("group", {
      name: workSv.unsortedRowFor(taskA.title),
    });

    await user.keyboard("7");

    expect(updateTask).not.toHaveBeenCalled();
  });

  it("unfolds the place picker on p", async () => {
    const user = userEvent.setup();
    render(
      <UnsortedView
        transport={makeTransport().transport}
        labels={workSv}
        onOpen={vi.fn()}
      />,
    );
    const first = await titleOf(taskA.title);
    const group = await screen.findByRole("group", {
      name: workSv.unsortedRowFor(taskA.title),
    });
    const pick = within(group.closest("li")!).getByRole("button", {
      name: taskPlaceLabelsSv.choosePlace,
    });
    expect(pick).toHaveAttribute("aria-expanded", "false");
    first.focus();

    await user.keyboard("p");

    expect(pick).toHaveAttribute("aria-expanded", "true");
  });
});

describe("UnsortedView without onOpen", () => {
  it("shows the title as text and ignores the number keys", async () => {
    const user = userEvent.setup();
    const { transport, updateTask } = makeTransport();
    render(<UnsortedView transport={transport} labels={workSv} />);

    const title = await screen.findByText(taskA.title);
    expect(title.closest("button")).toBeNull();
    expect(
      screen.queryByRole("button", { name: taskA.title }),
    ).not.toBeInTheDocument();
    expect(document.querySelector("ul[data-triage]")).toBeNull();
    const group = await screen.findByRole("group", {
      name: workSv.unsortedRowFor(taskA.title),
    });
    within(group).getByRole("button", { name: "Hem" }).focus();

    await user.keyboard("2");

    expect(updateTask).not.toHaveBeenCalled();
  });
});
