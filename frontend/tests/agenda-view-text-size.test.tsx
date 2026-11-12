import {
  act,
  fireEvent,
  render,
  waitFor,
  within,
} from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, expect, it, vi } from "vitest";
import { UndoMeta } from "@/features/work-app/agenda/agenda-undo";
import { workEn } from "@/features/work-app/shared/labels";
import type { WorkItemRecord } from "@/features/work-app/transport/transport";
import {
  task,
  other,
  makeTransport,
  renderAgenda,
  rowOf,
  resetAgendaEnvironment,
} from "./helpers/agenda-view-fixtures";

afterEach(resetAgendaEnvironment);

it("the row menu shows Status and Datum as open groups side by side at normal text, and as fold rows, one open at a time with Status first, at large text", async () => {
  const { transport } = makeTransport();
  const user = userEvent.setup();
  const width = window.innerWidth;
  try {
    // 270 px at a 16 px root is 16.9 rem: large text (the line is 17.25 rem).
    Object.defineProperty(window, "innerWidth", {
      value: 270,
      configurable: true,
      writable: true,
    });
    // A Task with a date, so Datum has a value to say when it is folded.
    const dated: WorkItemRecord = { ...task, due_at: "2030-01-15T09:00:00Z" };
    renderAgenda([dated, other], transport);
    fireEvent.contextMenu(rowOf(dated.title));
    const row = within(rowOf(dated.title));
    const status = row.getByRole("button", { name: /^Status/ });
    const date = row.getByRole("button", {
      name: new RegExp(`^${workEn.rescheduleRow}`),
    });
    expect(status).toHaveClass("sk-fold");
    expect(date).toHaveClass("sk-fold");
    expect(status).toHaveAttribute("aria-expanded", "true");
    expect(date).toHaveAttribute("aria-expanded", "false");
    expect(status).toHaveClass("work-agenda-menu-fold");
    expect(date).toHaveClass("work-agenda-menu-fold");
    // The value stands under a folded group only: the open Status shows it as its chosen chip.
    expect(status.querySelector(".sk-fold-meta")).toBeNull();
    expect(date.querySelector(".sk-fold-meta")).not.toBeNull();
    // × is one button of the panel, whatever the text size.
    expect(row.getAllByRole("button", { name: workEn.closeMenu })).toHaveLength(
      1,
    );
    expect(row.getByRole("group", { name: workEn.status })).toBeInTheDocument();
    expect(
      row.queryByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeNull();
    await user.click(date);
    expect(date).toHaveAttribute("aria-expanded", "true");
    expect(status).toHaveAttribute("aria-expanded", "false");
    expect(date.querySelector(".sk-fold-meta")).toBeNull();
    expect(status.querySelector(".sk-fold-meta")).not.toBeNull();
    expect(
      row.getByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeInTheDocument();
    expect(row.queryByRole("group", { name: workEn.status })).toBeNull();
  } finally {
    Object.defineProperty(window, "innerWidth", {
      value: width,
      configurable: true,
      writable: true,
    });
  }
});

/** Runs `body` with a window `width` px wide and a root font of `px`; the observers made meanwhile are returned to `body`. */
async function atTextSize(
  width: number,
  px: number,
  body: (resizeObservers: () => void) => void | Promise<void>,
) {
  const callbacks = new Set<() => void>();
  vi.stubGlobal(
    "ResizeObserver",
    class {
      private readonly cb: () => void;
      constructor(cb: () => void) {
        this.cb = cb;
      }
      observe() {
        callbacks.add(this.cb);
      }
      disconnect() {
        callbacks.delete(this.cb);
      }
      unobserve() {}
    },
  );
  const before = window.innerWidth;
  Object.defineProperty(window, "innerWidth", {
    value: width,
    configurable: true,
    writable: true,
  });
  document.documentElement.style.fontSize = `${px}px`;
  try {
    await body(() => act(() => callbacks.forEach((cb) => cb())));
  } finally {
    document.documentElement.style.fontSize = "";
    Object.defineProperty(window, "innerWidth", {
      value: before,
      configurable: true,
      writable: true,
    });
    vi.unstubAllGlobals();
  }
}

it("the row menu follows a change of the text size that fires no resize: 110 % to 200 % folds the groups, and back opens them", async () => {
  const { transport } = makeTransport();
  // 400 px at a 16 px root is 25 rem (110 %); at a 32 px root it is 12.5 rem (200 %).
  await atTextSize(400, 16, (observed) => {
    renderAgenda([task, other], transport);
    fireEvent.contextMenu(rowOf(task.title));
    const menu = () => within(rowOf(task.title));
    expect(rowOf(task.title).querySelector(".sk-fold")).toBeNull();
    expect(menu().getByRole("group", { name: workEn.status })).toBeVisible();
    expect(
      menu().getByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeVisible();
    // The root font grows: no resize event, only the observer of the probe reports.
    document.documentElement.style.fontSize = "32px";
    observed();
    expect(rowOf(task.title).querySelectorAll(".sk-fold")).toHaveLength(2);
    expect(menu().getByRole("group", { name: workEn.status })).toBeVisible();
    expect(
      menu().queryByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeNull();
    document.documentElement.style.fontSize = "16px";
    observed();
    expect(rowOf(task.title).querySelector(".sk-fold")).toBeNull();
    expect(
      menu().getByRole("group", { name: workEn.rescheduleGroup }),
    ).toBeVisible();
  });
});

it("at large text the groups are a fold: one open at a time, the date input goes with its group, the menu scrolls into view again at each change, and the value stands in the meta of a folded group only", async () => {
  const { transport } = makeTransport();
  const scroll = vi.fn();
  Object.defineProperty(HTMLElement.prototype, "scrollIntoView", {
    value: scroll,
    configurable: true,
    writable: true,
  });
  const dated: WorkItemRecord = { ...task, due_at: "2030-01-15T09:00:00Z" };
  try {
    await atTextSize(270, 16, async () => {
      const user = userEvent.setup();
      renderAgenda([dated, other], transport);
      fireEvent.contextMenu(rowOf(dated.title));
      const row = within(rowOf(dated.title));
      const asked = () => scroll.mock.calls.length;
      const atOpen = asked();
      expect(atOpen).toBeGreaterThan(0);
      const date = row.getByRole("button", {
        name: new RegExp(`^${workEn.rescheduleRow}`),
      });
      await user.click(date);
      expect(asked()).toBeGreaterThan(atOpen);
      // Open Datum: the Task's own date as the fifth chip (also at large text), the three shortcuts and the
      // Choose date… chip, which is the date input (no button of its own); an open group has no meta.
      const choices = row.getByRole("group", {
        name: workEn.rescheduleGroup,
      });
      expect(within(choices).getAllByRole("button")).toHaveLength(4);
      expect(within(choices).getByLabelText(workEn.rescheduleDate)).toHaveValue(
        "2030-01-15",
      );
      expect(date.querySelector(".sk-fold-meta")).toBeNull();
      // Status opens: Datum folds, its input goes with the group and the value stands in its meta again.
      const status = row.getByRole("button", { name: /^Status/ });
      const beforeStatus = asked();
      await user.click(status);
      expect(asked()).toBeGreaterThan(beforeStatus);
      expect(date).toHaveAttribute("aria-expanded", "false");
      expect(row.queryByLabelText(workEn.rescheduleDate)).toBeNull();
      expect(date.querySelector(".sk-fold-meta")).not.toBeNull();
      expect(status.querySelector(".sk-fold-meta")).toBeNull();
      // Opened again, it is there again with the Task's date.
      await user.click(date);
      expect(row.getByLabelText(workEn.rescheduleDate)).toHaveValue(
        "2030-01-15",
      );
    });
  } finally {
    Reflect.deleteProperty(HTMLElement.prototype, "scrollIntoView");
  }
});

it("at large text the date input is a focusable control of the row, and a chosen date leaves focus on a control of the row, not on the body", async () => {
  const { transport } = makeTransport();
  await atTextSize(270, 16, async () => {
    const user = userEvent.setup();
    renderAgenda([task, other], transport);
    fireEvent.contextMenu(rowOf(task.title));
    const row = within(rowOf(task.title));
    await user.click(
      row.getByRole("button", { name: new RegExp(`^${workEn.rescheduleRow}`) }),
    );
    // No click on a chip first: the input is there, over the chip, and takes the focus from the keys like any control.
    const field = row.getByLabelText(workEn.rescheduleDate);
    expect(field).not.toHaveAttribute("tabindex", "-1");
    act(() => field.focus());
    expect(field).toHaveFocus();
    fireEvent.change(field, { target: { value: "2030-01-15" } });
    // The move closes the menu: the input goes with it and the focus is handed to a control that stays.
    await waitFor(() =>
      expect(row.queryByLabelText(workEn.rescheduleDate)).toBeNull(),
    );
    await waitFor(() => {
      const active = document.activeElement as HTMLElement | null;
      expect(active).not.toBe(document.body);
      expect(rowOf(task.title).contains(active)).toBe(true);
    });
  });
});

it("the Task's own date is a chip in Datum at normal text, and the date input holds it in both sizes", async () => {
  const { transport } = makeTransport();
  const dated: WorkItemRecord = { ...task, due_at: "2030-01-15T09:00:00Z" };
  await atTextSize(400, 16, () => {
    renderAgenda([dated, other], transport);
    fireEvent.contextMenu(rowOf(dated.title));
    const choices = within(rowOf(dated.title)).getByRole("group", {
      name: workEn.rescheduleGroup,
    });
    // The date chip, Today, Tomorrow, Next week; Choose date… is the input, not a button.
    expect(within(choices).getAllByRole("button")).toHaveLength(4);
    expect(within(choices).getByLabelText(workEn.rescheduleDate)).toHaveValue(
      "2030-01-15",
    );
  });
});

it("the row menu at normal text has no fold rows: both groups are open", () => {
  const { transport } = makeTransport();
  renderAgenda([task, other], transport);
  fireEvent.contextMenu(rowOf(task.title));
  const row = within(rowOf(task.title));
  expect(row.getByRole("group", { name: workEn.status })).toBeInTheDocument();
  expect(
    row.getByRole("group", { name: workEn.rescheduleGroup }),
  ).toBeInTheDocument();
  expect(rowOf(task.title).querySelector(".sk-fold")).toBeNull();
});

/** Sets the window's scroll place for a test: jsdom does not scroll, so the test sets the value it reads. */
function setScrollY(y: number) {
  Object.defineProperty(window, "scrollY", {
    configurable: true,
    writable: true,
    value: y,
  });
}

/** Supplies scrollIntoView for one test and returns the spy; the caller removes it in `finally`. */
function stubScrollIntoView() {
  const scrollIntoView = vi.fn();
  Object.defineProperty(Element.prototype, "scrollIntoView", {
    configurable: true,
    writable: true,
    value: scrollIntoView,
  });
  return scrollIntoView;
}

/** A row's title beside its Undo line, as the row lays them out (the Undo line sits after the title). */
function undoRow(moving: boolean) {
  return (
    <div>
      <span>{task.title}</span>
      <UndoMeta
        text="Klar"
        labels={workEn}
        disabled={false}
        onUndo={vi.fn()}
        onExpire={vi.fn()}
        moving={moving}
      />
    </div>
  );
}

it("an Undo line whose change lands after the user has scrolled on is not scrolled to", () => {
  const scrollIntoView = stubScrollIntoView();
  setScrollY(0);
  try {
    const { rerender } = render(undoRow(true));
    // The line mounts while its change is written: it scrolls in once, as it always did.
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
    // The user scrolls on while the write runs, and the change lands after that: the page stays where it is.
    setScrollY(240);
    rerender(undoRow(false));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
    setScrollY(0);
  }
});

it("an Undo line whose change lands with no scroll since it was written is scrolled to, both ways nearest", () => {
  const scrollIntoView = stubScrollIntoView();
  setScrollY(0);
  try {
    const { rerender } = render(undoRow(true));
    rerender(undoRow(false));
    expect(scrollIntoView).toHaveBeenCalledTimes(2);
    expect(scrollIntoView).toHaveBeenLastCalledWith({
      block: "nearest",
      inline: "nearest",
    });
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});

it("an Undo line that has left the document is not scrolled to when its change lands", () => {
  const scrollIntoView = stubScrollIntoView();
  setScrollY(0);
  try {
    const { container, rerender } = render(undoRow(true));
    container.querySelector('p[role="status"]')?.remove();
    rerender(undoRow(false));
    expect(scrollIntoView).toHaveBeenCalledTimes(1);
  } finally {
    Reflect.deleteProperty(Element.prototype, "scrollIntoView");
  }
});
