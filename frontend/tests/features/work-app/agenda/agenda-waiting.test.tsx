import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";

/** 18 Nov 2026, 12:00 UTC (13:00 in Stockholm). */
const NOW = new Date("2026-11-18T12:00:00Z");
const ANDERS = "019f0000-0000-7000-8000-0000000000a9";

function waitingTask(overrides: Partial<WorkItemRecord> = {}): WorkItemRecord {
  return {
    kind: "task",
    id: "019f0000-0000-7000-8000-0000000000c1",
    title: "Svar från Anders om bildformat",
    status: "todo",
    version: 2,
    due_at: null,
    agenda_group: "overdue",
    waiting: true,
    waiting_since: "2026-11-13T09:00:00+01:00",
    waiting_on_contact_id: ANDERS,
    waiting_on_contact_name: "Anders",
    follow_up_at: "2026-11-17T09:00:00+01:00",
    follow_up_due: true,
    ...overrides,
  };
}

function renderAgenda(
  items: WorkItemRecord[],
  options: {
    filters?: WorkAgendaFrame["filters"];
    labels?: WorkLabels;
    transport?: WorkTransport;
    onOpen?: (frame: WorkFrame) => void;
    onChange?: (frame: WorkAgendaFrame) => void;
  } = {},
) {
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: options.filters ?? {},
    page: { items, next_cursor: null },
  };
  return render(
    <AgendaView
      frame={frame}
      onChange={options.onChange ?? vi.fn()}
      transport={options.transport ?? ({} as unknown as WorkTransport)}
      labels={options.labels ?? workSv}
      moves={0}
      onOpen={options.onOpen ?? vi.fn()}
      now={NOW}
    />,
  );
}

describe("a waiting Task in the dated agenda", () => {
  it("says who it waits on, since when, and that the follow-up is the reason it is listed", () => {
    renderAgenda([waitingTask()]);
    const row = screen.getByRole("listitem");
    // No due date of its own: the follow-up day put it here, so the meta line leads with it.
    expect(row.querySelector(".work-agenda-waiting")).toHaveTextContent(
      "Väntar på Anders sedan 13 nov",
    );
    expect(within(row).getByText("Följ upp igår")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
  });

  it("leads the meta line with the follow-up that places the row and moves the due date to the waiting line, each date once", () => {
    renderAgenda([waitingTask({ due_at: "2026-11-19T23:59:00+01:00" })]);
    const row = screen.getByRole("listitem");
    const lead = row.querySelector(".work-card-meta time");
    expect(lead).toHaveTextContent("Följ upp igår");
    expect(lead).toHaveAttribute("data-tone", "overdue");
    expect(within(row).queryByText("Imorgon")).toBeNull();
    expect(within(row).getAllByText(/förfaller imorgon/)).toHaveLength(1);
    expect(within(row).getAllByText(/Följ upp igår/i)).toHaveLength(1);
    const line = row.querySelector(".work-agenda-waiting");
    expect(line).toHaveTextContent("Väntar på Anders sedan 13 nov");
    expect(line).not.toHaveTextContent(/följ upp/i);
  });

  it("says the due day in English too", () => {
    renderAgenda([waitingTask({ due_at: "2026-11-19T23:59:00+01:00" })], {
      labels: workEn,
    });
    const row = screen.getByRole("listitem");
    expect(row.querySelector(".work-card-meta time")).toHaveTextContent(
      "Follow up yesterday",
    );
    expect(within(row).getAllByText(/due tomorrow/)).toHaveLength(1);
  });

  it("puts the wait first and the follow-up after it when the Task has an earlier due date", () => {
    renderAgenda([waitingTask({ due_at: "2026-11-16T23:59:00+01:00" })]);
    const row = screen.getByRole("listitem");
    // Two parts of one meta line: the "·" between them is drawn by CSS, not written.
    const parts = row.querySelectorAll(".work-agenda-waiting > span");
    expect([...parts].map((part) => part.textContent)).toEqual([
      "Väntar på Anders sedan 13 nov",
      "följ upp igår",
    ]);
    expect(row.querySelector(".work-agenda-waiting")).not.toHaveTextContent(
      "·",
    );
  });

  it("shows a follow-up that has not come in the plain tone, with its date", () => {
    renderAgenda([
      waitingTask({
        follow_up_at: "2026-11-25T09:00:00+01:00",
        follow_up_due: false,
        agenda_group: "upcoming",
      }),
    ]);
    const follow = screen.getByText("Följ upp 25 nov");
    expect(follow).not.toHaveAttribute("data-tone", "overdue");
  });

  it("reads in English with the English locale", () => {
    renderAgenda([waitingTask()], { labels: workEn });
    expect(screen.getByText("Follow up yesterday")).toBeInTheDocument();
    expect(
      screen.getByText("Waiting on Anders since 13 Nov"),
    ).toBeInTheDocument();
  });

  it("adds nothing to a Task that does not wait", () => {
    renderAgenda([
      waitingTask({ waiting: false, waiting_since: null, follow_up_at: null }),
    ]);
    expect(screen.queryByText(/Väntar på/)).toBeNull();
  });
});

describe("the waiting view", () => {
  it("opens the Contact from its name and shows the follow-up day", async () => {
    const onOpen = vi.fn();
    renderAgenda([waitingTask()], {
      filters: { waiting: "waiting" },
      onOpen,
    });
    expect(screen.getByText("Följ upp igår")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Anders" }));
    expect(onOpen).toHaveBeenCalledWith({ kind: "contact", id: ANDERS });
  });

  it("goes back to the dated agenda with 'Visa hela agendan', keeping the chosen tags", async () => {
    const getWorkAgenda = vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null });
    const onChange = vi.fn();
    renderAgenda([waitingTask()], {
      filters: { waiting: "waiting", tags: ["kund"] },
      transport: { getWorkAgenda } as unknown as WorkTransport,
      onChange,
    });
    await userEvent
      .setup()
      .click(screen.getByRole("button", { name: "Visa hela agendan" }));
    await waitFor(() =>
      expect(getWorkAgenda).toHaveBeenCalledWith({ tags: ["kund"] }),
    );
    expect(onChange).toHaveBeenCalledWith(
      expect.objectContaining({ filters: { tags: ["kund"] } }),
    );
  });

  it("is one press away from the agenda once some Task waits, and offers no switch otherwise", async () => {
    const getWorkAgenda = vi
      .fn()
      .mockResolvedValue({ items: [], next_cursor: null });
    const view = renderAgenda([waitingTask()], {
      transport: { getWorkAgenda } as unknown as WorkTransport,
    });
    const chip = screen.getByRole("button", { name: "Väntar på" });
    expect(chip).toHaveAttribute("aria-pressed", "false");
    await userEvent.setup().click(chip);
    await waitFor(() =>
      expect(getWorkAgenda).toHaveBeenCalledWith({ waiting: "waiting" }),
    );
    view.unmount();

    renderAgenda([waitingTask({ waiting: false, waiting_since: null })]);
    expect(screen.queryByRole("button", { name: "Väntar på" })).toBeNull();
  });
});
