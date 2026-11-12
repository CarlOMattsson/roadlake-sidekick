import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { cardLabelsEn } from "@/features/work-app/card-labels";
import { workEn } from "@/features/work-app/labels";
import { WorkCard } from "@/features/work-app/work-card";
import { WorkView } from "@/features/work-app/work-view";
import {
  rootFromToolResult,
  type WorkCardFrame,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport";

const TASK_ID = "019f0000-0000-7000-8000-000000000001";
const PROJECT_ID = "019f0000-0000-7000-8000-000000000002";
const DOMAIN_ID = "019f0000-0000-7000-8000-000000000003";

const task: WorkItemRecord = {
  kind: "task",
  id: TASK_ID,
  title: "Ring leverantören",
  status: "in_progress",
  due_at: null,
  version: 2,
};
const project: WorkItemRecord = {
  kind: "project",
  id: PROJECT_ID,
  title: "Renovering",
  status: "active",
  due_at: null,
  version: 1,
};
const domain: WorkItemRecord = {
  kind: "domain",
  id: DOMAIN_ID,
  title: "Ekonomi",
  status: "active",
  due_at: null,
  version: 1,
};

const frame: WorkCardFrame = {
  kind: "card",
  items: [task, project, domain],
  total: 3,
  truncated: false,
};

/** Reads the fullscreen Task view makes; they never answer, so only the call is checked. */
function transportWithPendingReads() {
  const getTask = vi.fn(() => new Promise<never>(() => undefined));
  const listTaskContacts = vi.fn(() => new Promise<never>(() => undefined));
  return {
    transport: {
      getTask,
      listTaskContacts,
    } as unknown as WorkTransport,
    getTask,
  };
}

describe("work card row titles in fullscreen", () => {
  it("makes a Task and a Project title a button that opens that record's frame", async () => {
    const user = userEvent.setup();
    const onOpenItem = vi.fn();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame}
        onOpenItem={onOpenItem}
      />,
    );

    await user.click(screen.getByRole("button", { name: "Ring leverantören" }));
    expect(onOpenItem).toHaveBeenLastCalledWith({ kind: "task", id: TASK_ID });

    await user.click(screen.getByRole("button", { name: "Renovering" }));
    expect(onOpenItem).toHaveBeenLastCalledWith({
      kind: "project",
      id: PROJECT_ID,
    });
    expect(onOpenItem).toHaveBeenCalledTimes(2);
  });

  it("keeps a record without a frame as plain text, not a button", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame}
        onOpenItem={vi.fn()}
      />,
    );

    expect(screen.getByText("Ekonomi")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Ekonomi" }),
    ).not.toBeInTheDocument();
  });

  it("keeps titles as plain text when no opener is given (inline)", () => {
    render(<WorkCard state="ready" labels={cardLabelsEn} frame={frame} />);

    expect(screen.getByText("Ring leverantören")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Ring leverantören" }),
    ).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Renovering" }),
    ).not.toBeInTheDocument();
  });

  it("in fullscreen, a title opens the Task inside the card view and Back returns to the card", async () => {
    const user = userEvent.setup();
    const { transport, getTask } = transportWithPendingReads();
    const initial = rootFromToolResult({
      card: {
        kind: "work_changes",
        items: [task, project, domain],
        total: 3,
        truncated: false,
      },
    });
    render(
      <WorkView
        transport={transport}
        initial={initial}
        labels={workEn}
        cardLabels={cardLabelsEn}
        shortcuts
      />,
    );

    await user.click(screen.getByRole("button", { name: "Ring leverantören" }));
    expect(getTask).toHaveBeenCalledWith(TASK_ID);
    expect(
      screen.getByRole("button", { name: /^Tillbaka till / }),
    ).toBeInTheDocument();

    await user.click(screen.getByRole("button", { name: /^Tillbaka till / }));
    expect(
      screen.getByRole("button", { name: "Ring leverantören" }),
    ).toBeInTheDocument();
  });
});
