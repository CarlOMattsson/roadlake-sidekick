import { render, screen } from "@testing-library/react";
import { expect, it, vi } from "vitest";
import { WorkView } from "@/features/work-app/work-view";
import { cardLabelsEn } from "@/features/work-app/card-labels";
import { workEn } from "@/features/work-app/labels";
import type {
  WorkContactRecord,
  WorkTaskSummary,
  WorkTransport,
} from "@/features/work-app/transport";

/*
 * The Tasks of a Contact (the "09" list, TaskSummaryList in the contact view) carry the same meta line as the other
 * rows: the time first, then the status. The date is in 2099, so the test does not depend on the clock.
 */

const anna: WorkContactRecord = {
  id: "019f0000-0000-7000-8000-0000000000c1",
  display_name: "Anna Andersson",
  email: null,
  phone: null,
  context_note: null,
  relationship: null,
  organization: null,
  role: null,
  address: null,
  aliases: [],
  archived: false,
  archived_at: null,
  version: 1,
};

const dueInProgress: WorkTaskSummary = {
  id: "019f0000-0000-7000-8000-0000000000a5",
  title: "Skriv offerten",
  status: "in_progress",
  due_at: "2099-01-15",
};

it("gives a Contact's Task its time before its status in the list's meta line", async () => {
  const work = {
    getContactContext: vi.fn().mockResolvedValue({
      contact: anna,
      projects: { items: [], next_cursor: null },
      tasks: { items: [dueInProgress], next_cursor: null },
    }),
  } as unknown as WorkTransport;
  render(
    <WorkView
      transport={work}
      initial={{ kind: "contact", id: anna.id }}
      labels={workEn}
      cardLabels={cardLabelsEn}
      fullscreen={vi.fn()}
    />,
  );

  const row = (await screen.findByText(dueInProgress.title)).closest("li");
  const parts = Array.from(
    row?.querySelector(".work-card-meta")?.children ?? [],
  );
  expect(parts).toHaveLength(2);
  // The time is the first part, the status the second.
  expect(parts[0]).toHaveClass("work-card-due");
  expect(parts[1]?.textContent).toBe(workEn.taskStatus.in_progress);
});
