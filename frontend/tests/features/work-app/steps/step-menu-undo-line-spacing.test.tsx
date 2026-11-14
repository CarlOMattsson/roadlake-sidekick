import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { applyHostStyle } from "@/features/mcp-apps/host-style";
import { UndoMeta } from "@/features/work-app/agenda/agenda-undo";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { manageLabelsSv } from "@/features/work-app/shared/manage-labels";
import { TaskSteps } from "@/features/work-app/tasks/task-steps";
import type {
  WorkStep,
  WorkTransport,
} from "@/features/work-app/transport/transport";

// The Step menu and its tip, Ångra's time line held while the pointer or focus is in it, and the spacing.
// How the spacing looks is measured in a browser (e2e/work-detail-styles-mcp-app.spec.ts), not read from the CSS.

// jsdom has no CSS global; the row controls use CSS.escape to find a control by its Step id.
if (!("CSS" in globalThis)) {
  vi.stubGlobal("CSS", { escape: (value: string) => value });
}

const TASK_ID = "019f0000-0000-7000-8000-0000000000a1";
const TIP_SV = "Håll inne ett steg för fler val.";
const TIP_KEYS_SV =
  "Högerklicka på ett steg eller tryck Shift+F10 för fler val.";
const TIP_EN = "Touch and hold a step for more options.";
const TIP_KEYS_EN = "Right-click a step or press Shift+F10 for more options.";

function step(id: string, title: string, version: number): WorkStep {
  return { id, title, status: "todo", due_at: null, version, position: 0 };
}
const stepA = step("019f0000-0000-7000-8000-0000000000b1", "Ring Anna", 1);
const stepB = step("019f0000-0000-7000-8000-0000000000b2", "Skriv offert", 2);
const sv = manageLabelsSv;

function renderSteps(items: WorkStep[], labels = workSv) {
  const transport = {
    listTaskSteps: vi.fn().mockResolvedValue({ items, next_cursor: null }),
    reorderTaskSteps: vi.fn(),
    archiveTaskStep: vi.fn(),
    restoreTaskStep: vi.fn(),
    completeTaskStep: vi.fn(),
    updateTaskStep: vi.fn(),
    createTaskStep: vi.fn(),
    listStepActions: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
  } as unknown as WorkTransport;
  return render(
    <TaskSteps taskId={TASK_ID} transport={transport} labels={labels} />,
  );
}

/** The Step's row (its `li`), found by its check. */
async function rowOf(title: string): Promise<HTMLElement> {
  const check = await screen.findByRole("checkbox", { name: title });
  return check.closest("li") as HTMLElement;
}

// The menu tip's storage is the document's dataset (for the session) and localStorage (kept across visits).
beforeEach(() => {
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

afterEach(() => {
  vi.restoreAllMocks();
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

describe("the Step menu opens from the row, not from a button", () => {
  it("gives the check Shift+F10 as its keyshortcut and the Step's data-manage key", async () => {
    renderSteps([stepA]);
    const check = await screen.findByRole("checkbox", { name: stepA.title });
    expect(check).toHaveAttribute("aria-keyshortcuts", "Shift+F10");
    expect(check).toHaveAttribute("data-manage", `${stepA.id}:more`);
  });

  it("a right click on the Step opens its menu, and a second one closes it", async () => {
    renderSteps([stepA, stepB]);
    const row = await rowOf(stepA.title);
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).not.toBeInTheDocument();

    fireEvent.contextMenu(row);
    expect(
      screen.getByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).toBeInTheDocument();
    // Only the Step right-clicked has its menu open.
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepB.title) }),
    ).not.toBeInTheDocument();

    fireEvent.contextMenu(row);
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).not.toBeInTheDocument();
  });

  it("the ContextMenu key opens the menu, and Shift+F10 opens it on another Step", async () => {
    renderSteps([stepA, stepB]);
    const checkA = await screen.findByRole("checkbox", { name: stepA.title });
    const checkB = screen.getByRole("checkbox", { name: stepB.title });

    fireEvent.keyDown(checkA, { key: "ContextMenu" });
    expect(
      screen.getByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).toBeInTheDocument();

    fireEvent.keyDown(checkB, { key: "F10", shiftKey: true });
    expect(
      screen.getByRole("button", { name: sv.archiveFor(stepB.title) }),
    ).toBeInTheDocument();
  });

  it("a plain F10 without Shift does not open the menu", async () => {
    renderSteps([stepA]);
    const check = await screen.findByRole("checkbox", { name: stepA.title });
    fireEvent.keyDown(check, { key: "F10" });
    expect(
      screen.queryByRole("button", { name: sv.archiveFor(stepA.title) }),
    ).not.toBeInTheDocument();
  });

  it("Escape closes an open Step menu", async () => {
    const user = userEvent.setup();
    renderSteps([stepA]);
    const check = await screen.findByRole("checkbox", { name: stepA.title });
    fireEvent.contextMenu(check.closest("li") as HTMLElement);
    expect(
      screen.getByRole("button", { name: sv.moveDownFor(stepA.title) }),
    ).toBeInTheDocument();

    check.focus();
    await user.keyboard("{Escape}");

    expect(
      screen.queryByRole("button", { name: sv.moveDownFor(stepA.title) }),
    ).not.toBeInTheDocument();
  });

  it("Escape from a choice inside the menu gives the focus back to the Step's check", async () => {
    const user = userEvent.setup();
    renderSteps([stepA, stepB]);
    const check = await screen.findByRole("checkbox", { name: stepA.title });
    fireEvent.contextMenu(check.closest("li") as HTMLElement);
    const choice = screen.getByRole("button", {
      name: sv.moveDownFor(stepA.title),
    });
    choice.focus();
    expect(choice).toHaveFocus();

    await user.keyboard("{Escape}");

    expect(check).toHaveFocus();
  });

  it("tells a screen reader how the Step menu opens (aria-description)", async () => {
    renderSteps([stepA]);
    const check = await screen.findByRole("checkbox", { name: stepA.title });
    expect(check.getAttribute("aria-description")).toBeTruthy();
  });
});

describe("the Step menu tip under the list", () => {
  it("shows the Swedish tip under the Steps when there are Steps", async () => {
    renderSteps([stepA]);
    await screen.findByRole("checkbox", { name: stepA.title });
    const tip = screen.getByText(TIP_SV);
    expect(tip.tagName).toBe("P");
    // The tip stands right after "+ Lägg till steg" (the add row follows the last step), not after the list.
    const add = within(tip.previousElementSibling as HTMLElement).getByRole(
      "button",
      { name: "Lägg till steg" },
    );
    expect(add).toHaveClass("work-add-row", "sk-action-row");
    expect(add.closest("div")?.previousElementSibling?.tagName).toBe("UL");
  });

  it("the tip is kept gone once the Step menu has been opened: the document and storage remember it", async () => {
    const { unmount } = renderSteps([stepA]);
    const row = await rowOf(stepA.title);

    // The Step's row keeps its own open state, so the drawn tip stays in the DOM until the list draws again; the
    // document's data-row-menu hides it (measured in tests/e2e/work-detail-styles-mcp-app.spec.ts).
    fireEvent.contextMenu(row);

    expect(document.documentElement.dataset.rowMenu).toBe("1");
    expect(localStorage.getItem("sidekick.rowMenuUsed")).toBe("1");
    unmount();
    delete document.documentElement.dataset.rowMenu;
    renderSteps([stepA]);
    await screen.findByRole("checkbox", { name: stepA.title });
    expect(screen.queryByText(TIP_SV)).not.toBeInTheDocument();
  });

  it("shows no tip when the Step list is empty", async () => {
    renderSteps([]);
    await screen.findByRole("button", { name: workSv.addStep });
    expect(screen.queryByText(TIP_SV)).not.toBeInTheDocument();
    expect(screen.queryByText(workSv.stepMenuHint)).not.toBeInTheDocument();
  });

  it("names the right click and Shift+F10 with a fine pointer, in Swedish and English", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(((query: string) => ({
      matches: query === "(pointer: fine)",
    })) as unknown as typeof window.matchMedia);
    const { unmount } = renderSteps([stepA]);
    await screen.findByRole("checkbox", { name: stepA.title });
    expect(screen.getByText(TIP_KEYS_SV)).toBeInTheDocument();
    unmount();

    renderSteps([stepA], workEn);
    await screen.findByRole("checkbox", { name: stepA.title });
    expect(screen.getByText(TIP_KEYS_EN)).toBeInTheDocument();
  });

  it("names the right click and Shift+F10 when the host reports a desktop, even where the frame's media query says coarse (ui-9)", async () => {
    vi.spyOn(window, "matchMedia").mockImplementation(((query: string) => ({
      matches: query === "(pointer: coarse)",
    })) as unknown as typeof window.matchMedia);
    const root = document.documentElement;
    applyHostStyle({ platform: "desktop" }, root);
    try {
      renderSteps([stepA], workEn);
      await screen.findByRole("checkbox", { name: stepA.title });
      expect(screen.getByText(TIP_KEYS_EN)).toBeInTheDocument();
      expect(screen.queryByText(TIP_EN)).not.toBeInTheDocument();
    } finally {
      delete root.dataset.hostPointer;
    }
  });

  it("shows the English tip with the English labels", async () => {
    renderSteps([stepA], workEn);
    await screen.findByRole("checkbox", { name: stepA.title });
    expect(screen.getByText(TIP_EN)).toBeInTheDocument();
    expect(screen.queryByText(TIP_SV)).not.toBeInTheDocument();
  });
});

describe("Ångra's time line stands still while the pointer or focus is in it", () => {
  function undoRow() {
    return (
      <div>
        <span>Skicka offert</span>
        <UndoMeta
          title="Skicka offert"
          text="Klar"
          labels={workSv}
          disabled={false}
          onUndo={vi.fn()}
          onExpire={vi.fn()}
        />
      </div>
    );
  }

  it("sets data-held while the pointer is over the line, and removes it when the pointer leaves", () => {
    render(undoRow());
    const wrapper = screen.getByRole("button", {
      name: `${workSv.agendaUndo} Skicka offert`,
    }).parentElement as HTMLElement;
    expect(wrapper).toHaveClass("work-agenda-undo");
    expect(wrapper).not.toHaveAttribute("data-held");

    fireEvent.pointerEnter(wrapper);
    expect(wrapper).toHaveAttribute("data-held");

    fireEvent.pointerLeave(wrapper);
    expect(wrapper).not.toHaveAttribute("data-held");
  });

  it("sets data-held while focus is in the line, and removes it on blur", () => {
    render(undoRow());
    const button = screen.getByRole("button", {
      name: `${workSv.agendaUndo} Skicka offert`,
    });
    const wrapper = button.parentElement as HTMLElement;

    act(() => button.focus());
    expect(wrapper).toHaveAttribute("data-held");

    act(() => button.blur());
    expect(wrapper).not.toHaveAttribute("data-held");
  });

  it("stays held while focus is in the line after the pointer has left", () => {
    render(undoRow());
    const button = screen.getByRole("button", {
      name: `${workSv.agendaUndo} Skicka offert`,
    });
    const wrapper = button.parentElement as HTMLElement;

    fireEvent.pointerEnter(wrapper);
    act(() => button.focus());
    fireEvent.pointerLeave(wrapper);
    expect(wrapper).toHaveAttribute("data-held");
  });
});
describe("locale parity of the Step menu tip", () => {
  it("has stepMenuHint and stepMenuKeys in both Swedish and English", () => {
    for (const labels of [workSv, workEn]) {
      expect(labels.stepMenuHint.length).toBeGreaterThan(0);
      expect(labels.stepMenuKeys.length).toBeGreaterThan(0);
    }
    expect(workSv.stepMenuHint).toBe(TIP_SV);
    expect(workSv.stepMenuKeys).toBe(TIP_KEYS_SV);
    expect(workEn.stepMenuHint).toBe(TIP_EN);
    expect(workEn.stepMenuKeys).toBe(TIP_KEYS_EN);
  });
});
