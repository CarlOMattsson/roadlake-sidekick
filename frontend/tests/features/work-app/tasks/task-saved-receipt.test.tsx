import { render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import { HostToolError } from "@/features/mcp-apps/bridge";
import type {
  WorkTask,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import { WorkView } from "@/features/work-app/view/work-view";

// A saved change is confirmed in the receipt bar at the view's foot ("Sparat", and for a date or clock change the date the
// chip now shows), never as a line in the content; a refused permission is a message box. Simulated-host tests (the view
// with a fake transport), not a real host.

// Wednesday 18 November 2026, 11:00 on the owner's clock (Europe/Stockholm, UTC+1).
const NOW = new Date("2026-11-18T10:00:00.000Z");
const AT_1730 = "2026-11-18T16:30:00.000Z";

const task: WorkTask = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Hämta paket på ICA",
  status: "todo",
  due_at: AT_1730,
  version: 1,
};

function transport(overrides: Record<string, unknown> = {}) {
  const updateTask = vi.fn((_id: string, version: number, changes: object) =>
    Promise.resolve({ task: { ...task, ...changes, version: version + 1 } }),
  );
  return {
    getTask: vi.fn().mockResolvedValue({ task }),
    listTaskContacts: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    listTaskSteps: vi.fn().mockResolvedValue({ items: [], next_cursor: null }),
    listTaskExternalReferences: vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null }),
    updateTask,
    ...overrides,
  } as unknown as WorkTransport;
}

function renderTask(work: WorkTransport, labels: WorkLabels) {
  return render(
    <WorkView
      transport={work}
      initial={{ kind: "task", id: task.id }}
      labels={labels}
    />,
  );
}

const slot = () => document.querySelector(".sk-receipt-slot") as HTMLElement;

beforeEach(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});
afterEach(() => {
  vi.useRealTimers();
});

describe.each([
  ["English", workEn, "Thu 19 Nov 5:30 pm"],
  ["Swedish", workSv, "tors 19 nov kl 17:30"],
] as const)("Saved after a due change (%s)", (_name, labels, chip) => {
  it("says Saved with the date the chip now shows, in the bar, with no line in the content", async () => {
    const user = userEvent.setup();
    const work = transport();
    renderTask(work, labels);
    await user.click(
      await screen.findByRole("button", {
        name: new RegExp(`^${labels.changeDue}`),
      }),
    );
    await user.click(screen.getByRole("button", { name: labels.dueTomorrow }));

    const message = await within(slot()).findByText(`${labels.saved}: ${chip}`);
    expect(message).toBeVisible();
    // No Ångra for a plain save, and no "Saved" line left in the content.
    expect(
      within(slot()).queryByRole("button", { name: labels.agendaUndo }),
    ).toBeNull();
    expect(
      screen
        .queryAllByText(labels.saved)
        .filter((node) => !node.closest(".sk-receipt-slot")),
    ).toHaveLength(0);
  });
});

describe("a refused permission", () => {
  it("is an info message box, not a bare line", async () => {
    const user = userEvent.setup();
    const work = transport({
      updateTask: vi.fn().mockRejectedValue(new HostToolError("forbidden")),
    });
    renderTask(work, workEn);
    await user.click(
      await screen.findByRole("button", {
        name: new RegExp(`^${workEn.changeDue}`),
      }),
    );
    await user.click(screen.getByRole("button", { name: workEn.dueTomorrow }));
    const message = await screen.findByText(workEn.forbiddenWrite);
    expect(message.closest(".sk-message")).toHaveClass("sk-message--info");
  });
});
