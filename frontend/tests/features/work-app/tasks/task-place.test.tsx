import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { placeChanges } from "@/features/work-app/hierarchy/group-choices";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import {
  taskPlaceLabelsEn,
  taskPlaceLabelsFor,
  taskPlaceLabelsSv,
} from "@/features/work-app/tasks/task-place-labels";
import type {
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

/*
 * The place chip of the Task page (the row "Plats" · "Renovering av köket" ⌄) and the repeat chip (a picker, read-only on the phone). The transports here
 * are simulated and not a real Claude or Android host; the phone case only imitates the companion's refusal of every
 * update_task but the completing one (supportsCall).
 */

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const HOME = "019f0000-0000-7000-8000-0000000000d1";
const KITCHEN = "019f0000-0000-7000-8000-0000000000c1";
const GARDEN = "019f0000-0000-7000-8000-0000000000c2";

const hierarchy = {
  kind: "hierarchy",
  truncated: false,
  nodes: [
    { kind: "domain", id: HOME, title: "Hem", parent_id: null },
    {
      kind: "project",
      id: KITCHEN,
      title: "Renovering av köket",
      parent_id: HOME,
    },
    { kind: "process", id: GARDEN, title: "Trädgård", parent_id: HOME },
  ],
};

type TaskFields = WorkTask & Record<string, unknown>;

function makeTask(extra: Record<string, unknown> = {}): TaskFields {
  return {
    id: TASK_ID,
    title: "Måla taket",
    status: "todo",
    due_at: null,
    version: 4,
    ...extra,
  };
}

function makeTransport(
  task: TaskFields,
  overrides: Partial<WorkTransport> = {},
) {
  const updateTask = vi.fn(
    (...args: [id: string, version: number, changes: unknown, key: string]) =>
      Promise.resolve({ task: { ...task, version: args[1] + 1 } }),
  );
  const work = {
    getTask: vi.fn().mockResolvedValue({ task }),
    getProject: vi.fn().mockResolvedValue({
      project: { id: KITCHEN, title: "Renovering av köket", status: "active" },
    }),
    getProcess: vi.fn().mockResolvedValue({
      process: { id: GARDEN, title: "Trädgård", status: "active" },
    }),
    getWorkHierarchy: vi.fn().mockResolvedValue(hierarchy),
    listProcessTasks: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask,
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
    ...overrides,
  };
  return { work: work as unknown as WorkTransport, updateTask };
}

function renderTask(work: WorkTransport, labels = workSv) {
  return render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: TASK_ID }}
      labels={labels}
    />,
  );
}

/** A property row: the name is aria-hidden (its own span), the value is its own span. */
function expectPropRow(row: HTMLElement, name: string, value: string) {
  expect(row.querySelector(".work-prop-label")?.textContent).toBe(name);
  expect(within(row).getByText(value)).toBeInTheDocument();
}

describe("the place chip of the Task page", () => {
  it("shows a Domain Task's place by the Domain's name, read from the hierarchy", async () => {
    const { work } = makeTransport(makeTask({ domain_id: HOME }));
    renderTask(work);

    expectPropRow(
      await screen.findByRole("button", { name: "Ändra plats: Hem" }),
      "Plats",
      "Hem",
    );
  });

  it("shows 'Att sortera' for a Task with no place and reads no hierarchy until the panel opens", async () => {
    const { work } = makeTransport(makeTask());
    const user = userEvent.setup();
    renderTask(work);

    const chip = await screen.findByRole("button", {
      name: "Ändra plats: Att sortera",
    });
    expectPropRow(chip, "Plats", "Att sortera");
    expect(work.getWorkHierarchy).not.toHaveBeenCalled();
    expect(chip).toHaveAttribute("aria-expanded", "false");

    await user.click(chip);
    expect(chip).toHaveAttribute("aria-expanded", "true");
    expect(
      await screen.findByRole("combobox", { name: "Plats för Måla taket" }),
    ).toHaveValue("");
    expect(work.getWorkHierarchy).toHaveBeenCalledTimes(1);
    // No Project or Process to open from a Task that has none.
    expect(screen.queryByRole("button", { name: /^Öppna/ })).toBeNull();
  });

  it("moves the Task to the chosen Process with one update_task against its version", async () => {
    const { work, updateTask } = makeTransport(
      makeTask({ project_id: KITCHEN, project_title: "Renovering av köket" }),
    );
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra plats: Renovering av köket",
      }),
    );
    const select = await screen.findByRole("combobox", {
      name: "Plats för Måla taket",
    });
    expect(select).toHaveValue(`project:${KITCHEN}`);
    await user.selectOptions(select, "Trädgård (process)");

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    const [id, version, changes, key] = updateTask.mock.calls[0]!;
    expect(id).toBe(TASK_ID);
    expect(version).toBe(4);
    expect(changes).toEqual(placeChanges({ kind: "process", id: GARDEN }));
    expect(typeof key).toBe("string");
    // The panel closes once the choice is made.
    await waitFor(() =>
      expect(screen.queryByRole("combobox")).not.toBeInTheDocument(),
    );
  });

  it("clears the place when 'Ingen plats' is chosen, and Escape closes the panel with focus on the chip", async () => {
    const { work, updateTask } = makeTransport(makeTask({ domain_id: HOME }));
    const user = userEvent.setup();
    renderTask(work);

    const chip = await screen.findByRole("button", {
      name: "Ändra plats: Hem",
    });
    await user.click(chip);
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(chip).toHaveFocus();

    await user.click(chip);
    await user.selectOptions(
      await screen.findByRole("combobox"),
      "Ingen plats (Att sortera)",
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual(placeChanges(null));
  });

  it("opens the Process page from the panel", async () => {
    const { work } = makeTransport(makeTask({ process_id: GARDEN }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", { name: "Ändra plats: Trädgård" }),
    );
    await user.click(screen.getByRole("button", { name: "Öppna Trädgård" }));
    expect(work.getProcess).toHaveBeenCalledWith(GARDEN);
  });

  it("is display and the open link only where the host cannot write the place (the phone)", async () => {
    const { work, updateTask } = makeTransport(
      makeTask({ project_id: KITCHEN, project_title: "Renovering av köket" }),
      {
        supportsTool: () => true,
        supportsCall: (name: string) => name !== "update_task",
      },
    );
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra plats: Renovering av köket",
      }),
    );
    expect(screen.queryByRole("combobox")).not.toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Öppna Renovering av köket" }),
    ).toBeInTheDocument();
    expect(updateTask).not.toHaveBeenCalled();
  });

  it("is plain text, not a button, when there is neither a write nor a page to open", async () => {
    const { work } = makeTransport(makeTask({ domain_id: HOME }), {
      supportsTool: () => true,
      supportsCall: (name: string) => name !== "update_task",
    });
    renderTask(work);

    const value = await screen.findByText("Hem");
    expect(value.closest("button")).toBeNull();
    expect(value.parentElement).toHaveClass("work-prop-static");
    expect(
      value.parentElement?.querySelector(".work-prop-label")?.textContent,
    ).toBe("Plats");
  });
});

describe("the repeat chip of the Task page", () => {
  const phone = {
    supportsTool: () => true,
    supportsCall: (name: string) => name !== "update_task",
  };

  it("says how the Task repeats, read-only on the phone, in Swedish and English", async () => {
    const rule = {
      frequency: "weekly",
      interval: 2,
      weekdays: [],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const first = makeTransport(makeTask({ recurrence: rule }), phone);
    const { unmount } = renderTask(first.work);
    const sv = await screen.findByText("Varannan vecka");
    expect(sv.closest("button")).toBeNull();
    expectPropRow(
      sv.parentElement as HTMLElement,
      "Upprepas",
      "Varannan vecka",
    );
    unmount();

    const second = makeTransport(makeTask({ recurrence: rule }), phone);
    renderTask(second.work, workEn);
    const en = await screen.findByText("Every other week");
    expect(en).toBeVisible();
    expectPropRow(
      en.parentElement as HTMLElement,
      "Repeats",
      "Every other week",
    );
  });

  it("shows no repeat chip on the phone for a Task that does not repeat", async () => {
    const { work } = makeTransport(makeTask({ recurrence: null }), phone);
    renderTask(work);
    await screen.findByText("Att sortera");
    expect(screen.queryByText(/Upprepas/)).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Ändra upprepning/ }),
    ).toBeNull();
  });

  it("offers 'Upprepas inte' as a chip where the host can write, and sets a weekly rule with one update_task", async () => {
    const { work, updateTask } = makeTransport(makeTask({ recurrence: null }));
    const user = userEvent.setup();
    renderTask(work);

    const chip = await screen.findByRole("button", {
      name: "Ändra upprepning: Upprepas aldrig",
    });
    expect(chip).toHaveAttribute("aria-expanded", "false");
    await user.click(chip);
    const group = within(
      screen.getByRole("group", { name: "Upprepning för Måla taket" }),
    );
    // One chip per rule, the current one ticked and focused, as the row menu's Status and Datum.
    const none = group.getByRole("button", { name: "Upprepas inte" });
    expect(none).toHaveAttribute("aria-pressed", "true");
    expect(none).toHaveFocus();
    expect(group.getAllByRole("button")).toHaveLength(7);
    await user.click(group.getByRole("button", { name: "Varje vecka" }));

    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    const [id, version, changes, key] = updateTask.mock.calls[0]!;
    expect(id).toBe(TASK_ID);
    expect(version).toBe(4);
    expect(changes).toEqual({ recurrence: { frequency: "weekly" } });
    expect(typeof key).toBe("string");
    await waitFor(() =>
      expect(
        screen.queryByRole("group", { name: "Upprepning för Måla taket" }),
      ).not.toBeInTheDocument(),
    );
  });

  it("changes a simple rule and removes one with null", async () => {
    const rule = {
      frequency: "daily",
      interval: 1,
      weekdays: [],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const { work, updateTask } = makeTransport(makeTask({ recurrence: rule }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas varje dag",
      }),
    );
    const group = within(
      screen.getByRole("group", { name: "Upprepning för Måla taket" }),
    );
    expect(group.getByRole("button", { name: "Varje dag" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    await user.click(group.getByRole("button", { name: "Varje månad" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({
      recurrence: { frequency: "monthly" },
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Ändra upprepning/ }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: /Ändra upprepning/ }));
    await user.click(
      within(
        screen.getByRole("group", { name: "Upprepning för Måla taket" }),
      ).getByRole("button", { name: "Upprepas inte" }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[1]?.[2]).toEqual({ recurrence: null });
  });

  it("keeps a rule the picker has no word for as its own option and writes nothing for it", async () => {
    const rule = {
      frequency: "weekly",
      interval: 3,
      weekdays: [1],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const { work, updateTask } = makeTransport(makeTask({ recurrence: rule }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas var 3:e vecka, tis",
      }),
    );
    const current = screen.getByRole("button", {
      name: "Upprepas var 3:e vecka, tis (nuvarande)",
    });
    expect(current).toHaveAttribute("aria-pressed", "true");
    await user.click(current);
    expect(updateTask).not.toHaveBeenCalled();
    // Choosing the current rule folds the chips away and gives the focus back to the chip.
    expect(
      screen.queryByRole("group", { name: "Upprepning för Måla taket" }),
    ).toBeNull();
  });

  it("offers every other week and the last weekday of the month, and sets each with one update_task", async () => {
    const { work, updateTask } = makeTransport(makeTask({ recurrence: null }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas aldrig",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Varannan vecka" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({
      recurrence: { frequency: "weekly", interval: 2 },
    });

    await waitFor(() =>
      expect(
        screen.getByRole("button", { name: /Ändra upprepning/ }),
      ).toBeEnabled(),
    );
    await user.click(screen.getByRole("button", { name: /Ändra upprepning/ }));
    await user.click(
      screen.getByRole("button", { name: "Sista vardagen i månaden" }),
    );
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(2));
    expect(updateTask.mock.calls[1]?.[2]).toEqual({
      recurrence: { frequency: "monthly", last_weekday: true },
    });
  });

  it("names a last-weekday rule and ticks its option", async () => {
    const rule = {
      frequency: "monthly",
      interval: 1,
      weekdays: [],
      day_of_month: null,
      last_weekday: true,
      until: null,
    };
    const { work } = makeTransport(makeTask({ recurrence: rule }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas sista vardagen i månaden",
      }),
    );
    expect(
      screen.getByRole("button", { name: "Sista vardagen i månaden" }),
    ).toHaveAttribute("aria-pressed", "true");
    // The weekday buttons belong to a weekly rule only.
    expect(
      screen.queryByRole("group", { name: "Veckodagar för Måla taket" }),
    ).toBeNull();
  });

  it("toggles the weekdays of a weekly rule, one update_task per tap, and shows them in words", async () => {
    const rule = {
      frequency: "weekly",
      interval: 1,
      weekdays: [0],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const { work, updateTask } = makeTransport(makeTask({ recurrence: rule }));
    const user = userEvent.setup();
    renderTask(work);

    expect(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas varje måndag",
      }),
    ).toBeInTheDocument();
    const days = within(
      screen.getByRole("group", { name: "Veckodagar för Måla taket" }),
    );
    expect(days.getAllByRole("button")).toHaveLength(7);
    expect(days.getByRole("button", { name: "måndag" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(days.getByRole("button", { name: "torsdag" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    await user.click(days.getByRole("button", { name: "torsdag" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({
      recurrence: { frequency: "weekly", interval: 1, weekdays: [0, 3] },
    });
  });

  it("keeps the chosen weekdays when the rule changes between weekly and every other week", async () => {
    const rule = {
      frequency: "weekly",
      interval: 1,
      weekdays: [0, 3],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const { work, updateTask } = makeTransport(makeTask({ recurrence: rule }));
    const user = userEvent.setup();
    renderTask(work);

    await user.click(
      await screen.findByRole("button", {
        name: "Ändra upprepning: Upprepas varje mån och tors",
      }),
    );
    await user.click(screen.getByRole("button", { name: "Varannan vecka" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    expect(updateTask.mock.calls[0]?.[2]).toEqual({
      recurrence: { frequency: "weekly", interval: 2, weekdays: [0, 3] },
    });
  });

  it("shows the weekday buttons in English and none on the phone", async () => {
    const rule = {
      frequency: "weekly",
      interval: 1,
      weekdays: [0, 3],
      day_of_month: null,
      last_weekday: false,
      until: null,
    };
    const first = makeTransport(makeTask({ recurrence: rule }));
    const { unmount } = renderTask(first.work, workEn);
    const days = within(
      await screen.findByRole("group", { name: "Repeat days for Måla taket" }),
    );
    expect(days.getByRole("button", { name: "Thursday" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(days.getByRole("button", { name: "Thursday" })).toHaveTextContent(
      "Thu",
    );
    unmount();

    const phone = makeTransport(makeTask({ recurrence: rule }), {
      supportsTool: () => true,
      supportsCall: (name: string) => name !== "update_task",
    });
    renderTask(phone.work);
    expect(await screen.findByText("Varje mån och tors")).toBeVisible();
    expect(screen.queryByRole("group", { name: /Veckodagar/ })).toBeNull();
  });

  it("closes on Escape with focus back on the chip, and speaks English", async () => {
    const { work } = makeTransport(makeTask({ recurrence: null }));
    const user = userEvent.setup();
    renderTask(work, workEn);

    const chip = await screen.findByRole("button", {
      name: "Change how often it repeats: Repeats never",
    });
    await user.click(chip);
    expect(
      screen.getByRole("button", { name: "Every month" }),
    ).toBeInTheDocument();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("group", { name: "Repeat settings for Måla taket" }),
    ).not.toBeInTheDocument();
    expect(chip).toHaveFocus();
  });
});

describe("the priority chip of the Task page", () => {
  it("unfolds Låg, Normal and Hög with Hög ticked, and choosing Normal writes one update_task", async () => {
    const { work, updateTask } = makeTransport(makeTask({ priority: "high" }));
    const user = userEvent.setup();
    renderTask(work);

    const chip = await screen.findByRole("button", {
      name: "Ändra prioritet: Hög",
    });
    expectPropRow(chip, "Prioritet", "Hög");
    await user.click(chip);
    const group = within(screen.getByRole("group", { name: "Prioritet" }));
    expect(group.getByRole("button", { name: "Låg" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(group.getByRole("button", { name: "Normal" })).toHaveAttribute(
      "aria-pressed",
      "false",
    );
    expect(group.getByRole("button", { name: "Hög" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );

    await user.click(group.getByRole("button", { name: "Normal" }));
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    const [id, version, changes, key] = updateTask.mock.calls[0]!;
    expect(id).toBe(TASK_ID);
    expect(version).toBe(4);
    expect(changes).toEqual({ priority: "normal" });
    expect(typeof key).toBe("string");
  });

  it("has no passive 'Prioritet:' chip beside the place where the host can write it", async () => {
    const { work } = makeTransport(makeTask({ priority: "high" }));
    const { container } = renderTask(work);

    await screen.findByRole("button", { name: "Ändra prioritet: Hög" });
    const passive = Array.from(
      container.querySelectorAll("p.work-chip"),
    ).filter((chip) => chip.textContent?.includes("Prioritet"));
    expect(passive).toHaveLength(0);
  });
});

describe("the wording of the repeat rule", () => {
  const rule = (
    frequency: "daily" | "weekly" | "monthly" | "yearly",
    interval: number,
  ) => ({ frequency, interval });

  it("covers all four frequencies in Swedish, with the right ordinal", () => {
    const sv = taskPlaceLabelsSv.repeats;
    expect(sv(rule("daily", 1))).toBe("Upprepas varje dag");
    expect(sv(rule("weekly", 1))).toBe("Upprepas varje vecka");
    expect(sv(rule("monthly", 1))).toBe("Upprepas varje månad");
    expect(sv(rule("yearly", 1))).toBe("Upprepas varje år");
    expect(sv(rule("weekly", 2))).toBe("Upprepas varannan vecka");
    expect(sv(rule("yearly", 2))).toBe("Upprepas vartannat år");
    expect(sv(rule("weekly", 3))).toBe("Upprepas var 3:e vecka");
    expect(sv(rule("daily", 3))).toBe("Upprepas var 3:e dag");
    expect(sv(rule("monthly", 11))).toBe("Upprepas var 11:e månad");
    expect(sv(rule("daily", 21))).toBe("Upprepas var 21:a dag");
  });

  it("covers all four frequencies in English", () => {
    const en = taskPlaceLabelsEn.repeats;
    expect(en(rule("daily", 1))).toBe("Repeats daily");
    expect(en(rule("weekly", 1))).toBe("Repeats weekly");
    expect(en(rule("monthly", 1))).toBe("Repeats monthly");
    expect(en(rule("yearly", 1))).toBe("Repeats yearly");
    expect(en(rule("weekly", 2))).toBe("Repeats every other week");
    expect(en(rule("weekly", 3))).toBe("Repeats every 3 weeks");
    expect(en(rule("yearly", 3))).toBe("Repeats every 3 years");
  });

  it("names weekdays, the last weekday and a day of the month in both languages", () => {
    const sv = taskPlaceLabelsSv.repeatsShort;
    const en = taskPlaceLabelsEn.repeatsShort;
    const weekly = (weekdays: number[], interval = 1) => ({
      frequency: "weekly" as const,
      interval,
      weekdays,
    });
    expect(sv(weekly([0]))).toBe("varje måndag");
    expect(sv(weekly([3, 0]))).toBe("varje mån och tors");
    expect(sv(weekly([0, 2, 4]))).toBe("varje mån, ons och fre");
    expect(sv(weekly([0, 1, 2, 3, 4, 5, 6]))).toBe("varje dag");
    expect(sv(weekly([0, 3], 2))).toBe("varannan vecka, mån och tors");
    expect(en(weekly([0]))).toBe("every Monday");
    expect(en(weekly([3, 0]))).toBe("every Mon and Thu");
    expect(en(weekly([0, 2, 4]))).toBe("every Mon, Wed and Fri");
    expect(en(weekly([0, 3], 2))).toBe("every other week, Mon and Thu");

    const last = {
      frequency: "monthly" as const,
      interval: 1,
      last_weekday: true,
    };
    expect(sv(last)).toBe("sista vardagen i månaden");
    expect(en(last)).toBe("on the last weekday of the month");
    expect(sv({ ...last, interval: 2 })).toBe("sista vardagen varannan månad");
    expect(en({ ...last, interval: 2 })).toBe(
      "on the last weekday of every other month",
    );
    expect(taskPlaceLabelsEn.repeats(last)).toBe(
      "Repeats on the last weekday of the month",
    );

    const day = {
      frequency: "monthly" as const,
      interval: 1,
      day_of_month: 21,
    };
    expect(sv(day)).toBe("varje månad den 21:a");
    expect(en(day)).toBe("monthly on the 21st");
    expect(en({ ...day, day_of_month: 12 })).toBe("monthly on the 12th");
  });

  it("keeps identical keys in both languages", () => {
    expect(Object.keys(taskPlaceLabelsEn).sort()).toEqual(
      Object.keys(taskPlaceLabelsSv).sort(),
    );
    expect(taskPlaceLabelsFor("sv-SE")).toBe(taskPlaceLabelsSv);
    expect(taskPlaceLabelsFor("en-GB")).toBe(taskPlaceLabelsEn);
  });
});
