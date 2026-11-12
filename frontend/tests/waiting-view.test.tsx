import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { AgendaView } from "@/features/work-app/agenda/agenda";
import { AgendaSummary } from "@/features/work-app/inline/inline-summary";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  workEn,
  workSv,
  type WorkLabels,
} from "@/features/work-app/shared/labels";
import type {
  WorkAgendaFrame,
  WorkItemRecord,
  WorkTransport,
} from "@/features/work-app/transport/transport";
import {
  remindAt,
  waitedDays,
  waitingRows,
} from "@/features/work-app/shared/waiting";
import { readStylesheet } from "./helpers/stylesheet";

/** 27 Oct 2026, 12:00 UTC (Stockholm is still on summer time until 25 Oct, so 13:00 on the 27th). */
const NOW = new Date("2026-10-27T12:00:00Z");

function waiting(
  id: string,
  title: string,
  since: string | null,
  name: string | null,
): WorkItemRecord {
  return {
    kind: "task",
    id,
    title,
    status: "todo",
    version: 2,
    agenda_group: "upcoming",
    waiting: true,
    waiting_since: since,
    waiting_on_contact_name: name,
  };
}

const anna = waiting(
  "019f0000-0000-7000-8000-0000000000c1",
  "Förbered demo",
  "2026-10-18T09:00:00+02:00",
  "Anna Berg",
);
const recent = waiting(
  "019f0000-0000-7000-8000-0000000000c2",
  "Skicka ritningar",
  "2026-10-26T09:00:00+01:00",
  "Sara Holm",
);
const nameless = waiting(
  "019f0000-0000-7000-8000-0000000000c3",
  "Svar från banken",
  "2026-10-25T09:00:00+01:00",
  null,
);

function renderWaiting(
  items: WorkItemRecord[],
  transport: WorkTransport,
  labels: WorkLabels = workEn,
) {
  const frame: WorkAgendaFrame = {
    kind: "agenda",
    filters: { waiting: "waiting" },
    page: { items, next_cursor: null },
  };
  return render(
    <AgendaView
      frame={frame}
      onChange={vi.fn()}
      transport={transport}
      labels={labels}
      moves={0}
      onOpen={vi.fn()}
      now={NOW}
    />,
  );
}

function makeTransport() {
  const updateTask = vi.fn((id: string, version: number) =>
    Promise.resolve({
      task: {
        id,
        title: "",
        status: "todo",
        due_at: null,
        version: version + 1,
      },
    }),
  );
  return {
    transport: { updateTask, getTask: vi.fn() } as unknown as WorkTransport,
    updateTask,
  };
}

describe("waiting helpers", () => {
  it("counts calendar days on the Stockholm calendar", () => {
    expect(waitedDays("2026-10-18T09:00:00+02:00", NOW)).toBe(9);
    expect(waitedDays("2026-10-27T01:00:00+01:00", NOW)).toBe(0);
    expect(waitedDays(null, NOW)).toBeNull();
    expect(waitedDays("not a date", NOW)).toBeNull();
  });

  it("orders the longest wait first and puts undated records last", () => {
    const undated = waiting("u", "Utan datum", null, "Bo");
    const rows = waitingRows([undated, recent, anna, nameless], NOW);
    expect(rows.map((row) => row.item.title)).toEqual([
      "Förbered demo",
      "Svar från banken",
      "Skicka ritningar",
      "Utan datum",
    ]);
    expect(rows[0]).toMatchObject({ who: "Anna Berg", days: 9 });
    expect(rows[1]?.who).toBeNull();
  });

  it("sets a reminder to 09:00 the next local morning", () => {
    const at = new Date(remindAt(NOW));
    const expected = new Date(NOW);
    expected.setDate(expected.getDate() + 1);
    expected.setHours(9, 0, 0, 0);
    expect(at.getTime()).toBe(expected.getTime());
  });
});

describe("waiting view in the fullscreen agenda", () => {
  it("shows who is waited on and for how long, the longest wait first", () => {
    renderWaiting([recent, anna, nameless], makeTransport().transport);
    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(3);
    expect(within(rows[0]!).getByText("Anna Berg")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("9 days")).toBeInTheDocument();
    expect(within(rows[0]!).getByText("Förbered demo")).toBeInTheDocument();
    expect(within(rows[1]!).getByText("Someone")).toBeInTheDocument();
    expect(within(rows[2]!).getByText("1 day")).toBeInTheDocument();
    expect(screen.getByText("Waiting on · 3")).toBeInTheDocument();
    // It is not the dated agenda: no group such as "Overdue" or "No date".
    expect(screen.queryByText(/Undated|No date|Later/)).toBeNull();
  });

  it("speaks Swedish with the Swedish labels", () => {
    renderWaiting([anna], makeTransport().transport, workSv);
    expect(screen.getByText("Du väntar på · 1")).toBeInTheDocument();
    expect(screen.getByText("9 dagar")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Påminn mig imorgon/ }),
    ).toBeVisible();
  });

  it("says so when nobody is waited on", () => {
    renderWaiting([], makeTransport().transport);
    expect(
      screen.getByText("You’re not waiting on anyone."),
    ).toBeInTheDocument();
  });

  it("reminds with update_task: follow_up_at is set to tomorrow morning", async () => {
    const { transport, updateTask } = makeTransport();
    renderWaiting([anna], transport);
    const button = screen.getByRole("button", {
      name: "Remind me tomorrow about Förbered demo",
    });
    await userEvent.click(button);
    await waitFor(() => expect(updateTask).toHaveBeenCalledTimes(1));
    const [id, version, changes, key] = updateTask.mock.calls[0] as unknown as [
      string,
      number,
      { follow_up_at: string },
      string,
    ];
    expect(id).toBe(anna.id);
    expect(version).toBe(2);
    expect(changes).toEqual({ follow_up_at: remindAt(NOW) });
    expect(key).toBeTruthy();
    expect(
      await screen.findByText("Reminder set for tomorrow at 09:00"),
    ).toBeInTheDocument();
    expect(button).toBeDisabled();
  });

  it("keeps the dated agenda for an agenda read without the waiting filter", () => {
    const frame: WorkAgendaFrame = {
      kind: "agenda",
      filters: {},
      page: { items: [anna], next_cursor: null },
    };
    render(
      <AgendaView
        frame={frame}
        onChange={vi.fn()}
        transport={makeTransport().transport}
        labels={workEn}
        moves={0}
        onOpen={vi.fn()}
        now={NOW}
      />,
    );
    expect(screen.queryByRole("button", { name: /Remind me/ })).toBeNull();
  });

  it("gives the reminder button a 44 px touch target and lets the row wrap at 320 px", () => {
    const css = readStylesheet("features/work-app/agenda/agenda.css");

    expect(css.rule(".sidekick-work .work-waiting-remind")).toMatchObject({
      "min-height": "2.75rem",
      "min-width": "2.75rem",
      "max-width": "100%",
    });
    expect(css.rule(".sidekick-work .work-waiting-who")["flex-wrap"]).toBe(
      "wrap",
    );
  });
});

describe("waiting view in the inline card", () => {
  // The card reads the clock on every render, so the clock is fixed to NOW.
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(NOW);
  });
  afterEach(() => {
    vi.useRealTimers();
  });

  it("lists who and how long, then the Task, without a reminder button", () => {
    render(
      <AgendaSummary
        page={{ items: [recent, anna], next_cursor: null }}
        filters={{ waiting: "waiting" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("region", { name: "Waiting on" }),
    ).toBeInTheDocument();
    expect(screen.getByText("2 waiting")).toBeInTheDocument();
    const rows = screen.getAllByRole("listitem");
    expect(rows[0]).toHaveTextContent("Anna Berg · 9 days");
    expect(rows[0]).toHaveTextContent("Förbered demo");
    expect(rows[1]).toHaveTextContent("Sara Holm · 1 day");
    expect(screen.getAllByRole("button")).toHaveLength(1);
    expect(
      screen.getByRole("button", { name: /^Show all \(\d+\)$/ }),
    ).toBeInTheDocument();
  });

  it("is Swedish and says when nobody is waited on", () => {
    const { rerender } = render(
      <AgendaSummary
        page={{ items: [anna], next_cursor: null }}
        filters={{ waiting: "waiting" }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 väntar")).toBeInTheDocument();
    expect(screen.getByText("Anna Berg · 9 dagar")).toBeInTheDocument();
    rerender(
      <AgendaSummary
        page={{ items: [], next_cursor: null }}
        filters={{ waiting: "waiting" }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Du väntar inte på någon.")).toBeInTheDocument();
  });

  it("is the dated agenda card without the waiting filter", () => {
    render(
      <AgendaSummary
        page={{ items: [anna], next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "Agenda" })).toBeInTheDocument();
  });
});
