import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import { AgendaSummary } from "@/features/work-app/inline/inline-summary";
import { type WorkItemRecord } from "@/features/work-app/transport/transport";
import {
  agendaItems,
  installFixedClock,
} from "./helpers/inline-summary-fixtures";

installFixedClock();

describe("inline agenda summary", () => {
  it("titles the card with the overdue and today counts, under the app name and today's date", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "Agenda" })).toBeInTheDocument();
    // The kicker is the app name and today's date (the fixed clock is Sun 25 Oct); the counts are the title.
    expect(screen.getByText("Work · Sun 25 Oct")).toBeInTheDocument();
    expect(screen.getByText("1 today, 2 overdue")).toBeInTheDocument();
  });

  it("uses the Swedish kicker, title and Open label for a Swedish host", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByRole("region", { name: "Agenda" })).toBeInTheDocument();
    expect(screen.getByText("Arbete · sön 25 okt")).toBeInTheDocument();
    expect(screen.getByText("1 idag, 2 försenade")).toBeInTheDocument();
    // The Open button is "Öppna Agenda"; its foot counts the one page row the card leaves out.
    expect(
      screen.getAllByRole("button", { name: /^Öppna Agenda/ }),
    ).toHaveLength(1);
    expect(screen.getByText("· 1 fler")).toHaveClass("work-compact-more");
  });

  it("titles one overdue record in the singular form of its words, and says more exist when another page exists", () => {
    const { unmount } = render(
      <AgendaSummary
        page={{ items: agendaItems.slice(0, 1), next_cursor: "next" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 overdue, more not shown")).toBeInTheDocument();
    unmount();
    render(
      <AgendaSummary
        page={{ items: agendaItems.slice(0, 1), next_cursor: "next" }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 försenad, fler finns")).toBeInTheDocument();
  });

  it("says more exist in the title when another page exists, without a + sign", () => {
    const { container } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: "next" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByText("1 today, 2 overdue, more not shown"),
    ).toBeInTheDocument();
    expect(container.textContent).not.toContain("3+");
  });

  it("labels the overdue rows after today's row with Overdue / Försenade, in two lists, and leaves the label out when only one group is shown", () => {
    const { container, rerender } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    // Both groups are named: "Today" over today's row, "Overdue" over the overdue rows.
    const groups = container.querySelectorAll("p.work-compact-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("Today");
    const label = groups[1];
    expect(label).toHaveTextContent("Overdue");
    const lists = container.querySelectorAll("ul.work-compact-rows");
    expect(lists).toHaveLength(2);
    // Today's label, today's row, then the label, then the overdue rows.
    expect(groups[0]?.nextElementSibling).toBe(lists[0]);
    expect(lists[0]).toHaveTextContent("Skriv offerten");
    expect(lists[0]?.querySelectorAll("li")).toHaveLength(1);
    expect(label?.previousElementSibling).toBe(lists[0]);
    expect(label?.nextElementSibling).toBe(lists[1]);
    expect(lists[1]).toHaveTextContent("Betala faktura");
    expect(inlineSummaryLabelsSv.agendaOverdueLabel).toBe("Försenade");
    rerender(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(
      container.querySelectorAll("p.work-compact-group")[1],
    ).toHaveTextContent("Försenade");
    rerender(
      <AgendaSummary
        page={{ items: agendaItems.slice(0, 2), next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(container.querySelector("p.work-compact-group")).toBeNull();
    expect(container.querySelectorAll("ul.work-compact-rows")).toHaveLength(1);
  });

  it("draws every row of today above the Försenade label, whatever order the rows were chosen in: two for today and one overdue", () => {
    const second: WorkItemRecord = {
      kind: "task",
      id: "019f0000-0000-7000-8000-0000000000a5",
      title: "Skicka fakturan",
      status: "todo",
      due_at: "2026-10-25T16:00:00Z",
      agenda_group: "today" as const,
    };
    const { container } = render(
      <AgendaSummary
        page={{
          items: [agendaItems[0]!, agendaItems[2]!, second],
          next_cursor: null,
        }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    const lists = container.querySelectorAll("ul.work-compact-rows");
    expect(lists).toHaveLength(2);
    expect(lists[0]?.querySelectorAll("li")).toHaveLength(2);
    expect(lists[0]).toHaveTextContent("Skriv offerten");
    expect(lists[0]).toHaveTextContent("Skicka fakturan");
    expect(lists[0]).not.toHaveTextContent("Betala faktura");
    const groups = container.querySelectorAll("p.work-compact-group");
    expect(groups).toHaveLength(2);
    expect(groups[0]).toHaveTextContent("Idag");
    const label = groups[1];
    expect(label).toHaveTextContent("Försenade");
    expect(label?.previousElementSibling).toBe(lists[0]);
    expect(lists[1]?.querySelectorAll("li")).toHaveLength(1);
    expect(lists[1]).toHaveTextContent("Betala faktura");
    expect(lists[1]).not.toHaveTextContent("Skicka fakturan");
  });

  it("writes the Swedish singular for one overdue record, with no zero count for today", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems.slice(0, 1), next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 försenad")).toBeInTheDocument();
    expect(screen.queryByText(/idag/)).toBeNull();
  });

  it("says nothing is overdue or due today when the agenda has no groups, with no meta line and no button", () => {
    const flat = agendaItems.map((item) => ({ ...item, agenda_group: null }));
    const { container } = render(
      <AgendaSummary
        page={{ items: flat, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("Agenda")).toBeInTheDocument();
    expect(
      screen.getByText("Nothing overdue or due today."),
    ).toBeInTheDocument();
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(0);
    expect(container.querySelector(".sk-card__meta")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("counts the upcoming records in a meta line under the sentence, and offers the agenda", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const upcoming = agendaItems.filter(
      (item) => item.agenda_group === "upcoming",
    );
    render(
      <AgendaSummary
        page={{ items: upcoming, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
      />,
    );
    expect(screen.getByText("Agenda")).toBeInTheDocument();
    expect(
      screen.getByText("Nothing overdue or due today."),
    ).toBeInTheDocument();
    expect(screen.getByText("1 upcoming")).toHaveClass("sk-card__meta");
    // Upcoming records are not listed inline.
    expect(screen.queryByText("Städa garaget")).toBeNull();
    await user.click(screen.getByRole("button", { name: "Open Agenda" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("counts every group that is neither overdue nor today in the meta line", () => {
    const later: WorkItemRecord = {
      kind: "project",
      id: "019f0000-0000-7000-8000-0000000000a5",
      title: "Sommarfest",
      status: "active",
      due_at: null,
      agenda_group: "scheduled_later",
    };
    const upcoming = agendaItems.filter(
      (item) => item.agenda_group === "upcoming",
    );
    render(
      <AgendaSummary
        page={{ items: [...upcoming, later], next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("2 upcoming")).toHaveClass("sk-card__meta");
  });

  it("uses the Swedish empty sentence and meta line for a Swedish host", () => {
    const upcoming = agendaItems.filter(
      (item) => item.agenda_group === "upcoming",
    );
    render(
      <AgendaSummary
        page={{ items: upcoming, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Inget försenat och inget för idag."),
    ).toBeInTheDocument();
    expect(screen.getByText("1 kommande")).toHaveClass("sk-card__meta");
  });

  it("says more on the agenda in the meta line when nothing is listed and another page exists", () => {
    const { unmount } = render(
      <AgendaSummary
        page={{ items: [], next_cursor: "next" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Nothing overdue or due today."),
    ).toBeInTheDocument();
    expect(screen.getByText("more on the agenda")).toHaveClass("sk-card__meta");
    expect(
      screen.getByRole("button", { name: "Open Agenda" }),
    ).toBeInTheDocument();
    unmount();
    render(
      <AgendaSummary
        page={{ items: [], next_cursor: "next" }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("fler på agendan")).toHaveClass("sk-card__meta");
  });

  it("keeps the upcoming count and says more on the agenda while another page may hold more", () => {
    const upcoming = agendaItems.filter(
      (item) => item.agenda_group === "upcoming",
    );
    render(
      <AgendaSummary
        page={{ items: upcoming, next_cursor: "next" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 upcoming, more on the agenda")).toHaveClass(
      "sk-card__meta",
    );
    expect(
      screen.getByText("Nothing overdue or due today."),
    ).toBeInTheDocument();
  });

  it("shows no Open button when the agenda has no overdue, today, upcoming or further record", () => {
    render(
      <AgendaSummary
        page={{ items: [], next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByText("Nothing overdue or due today."),
    ).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("lists every overdue or today record as a row, with the Open button beside the rows", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    const shown = agendaItems.filter(
      (item) => item.agenda_group !== "upcoming",
    );
    const { container } = render(
      <AgendaSummary
        page={{ items: shown, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={onOpen}
      />,
    );
    expect(
      container.querySelectorAll(
        "li.work-compact-row > button.work-compact-open",
      ),
    ).toHaveLength(3);
    // Three row buttons and the Open button.
    expect(screen.getAllByRole("button")).toHaveLength(4);
    await user.click(screen.getByRole("button", { name: "Open Agenda" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("offers one Open, also when records of the other groups are left out", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getAllByRole("button", { name: /^Open Agenda/ }),
    ).toHaveLength(1);
  });

  it("lists the overdue and today records only, and leaves the upcoming ones out of the title", () => {
    render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("1 today, 2 overdue")).toBeInTheDocument();
    expect(screen.queryByText("Städa garaget")).toBeNull();
    expect(screen.queryByText(/upcoming/)).toBeNull();
  });

  it("lists today's record first and then the overdue ones, as rows with their due words under the labels Today and Overdue", () => {
    const { container } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    // A Task due today stands first, then the overdue records oldest first.
    expect(titles).toEqual(["Skriv offerten", "Betala faktura", "Ring Anna"]);
    // Overdue due words are red. Today's row says nothing of the day: the label "Today" over it says so.
    expect(screen.getByText("5 days overdue")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    expect(screen.getByText("4 days overdue")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    expect(container.querySelector('time[data-tone="today"]')).toBeNull();
    expect(
      [...container.querySelectorAll("p.work-compact-group")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["Today", "Overdue"]);
    // No status glyphs and no other headings.
    expect(screen.queryByText("Start with")).toBeNull();
    expect(screen.queryByText("More overdue")).toBeNull();
    expect(container.querySelector(".work-agenda-glyph")).toBeNull();
  });

  it("lists the Swedish rows under no headings, today's first, with the due words in Swedish", () => {
    const { container } = render(
      <AgendaSummary
        page={{ items: agendaItems, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    const titles = [
      ...container.querySelectorAll(".work-compact-row-title"),
    ].map((node) => node.textContent);
    expect(titles).toEqual(["Skriv offerten", "Betala faktura", "Ring Anna"]);
    expect(screen.getByText("5 dagar försenad")).toHaveAttribute(
      "data-tone",
      "overdue",
    );
    // Today's row names no day: the label "Idag" over it stands instead.
    expect(container.querySelector('time[data-tone="today"]')).toBeNull();
    expect(
      [...container.querySelectorAll("p.work-compact-group")].map(
        (node) => node.textContent,
      ),
    ).toEqual(["Idag", "Försenade"]);
    expect(screen.queryByText("Börja med")).toBeNull();
    expect(screen.queryByText("Fler försenade")).toBeNull();
  });

  it("lists at most three rows, and the title counts all of the overdue records", () => {
    const overdue: WorkItemRecord[] = Array.from({ length: 6 }, (_, index) => ({
      kind: "task",
      id: `019f0000-0000-7000-8000-0000000000${index}0`,
      title: `Uppgift ${index + 1}`,
      status: "todo",
      due_at: "2026-10-20T09:00:00Z",
      agenda_group: "overdue" as const,
    }));
    const { container } = render(
      <AgendaSummary
        page={{ items: overdue, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
    expect(screen.getByText("6 overdue")).toBeInTheDocument();
    expect(screen.queryByText("Uppgift 4")).toBeNull();
  });

  it("says in one line under the rows how many overdue records the card leaves out", () => {
    const overdue: WorkItemRecord[] = Array.from({ length: 6 }, (_, index) => ({
      kind: "task",
      id: `019f0000-0000-7000-8000-0000000000${index}0`,
      title: `Uppgift ${index + 1}`,
      status: "todo",
      due_at: "2026-10-20T09:00:00Z",
      agenda_group: "overdue" as const,
    }));
    const { container } = render(
      <AgendaSummary
        page={{ items: overdue, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    // Three rows shown of six overdue: the foot names the three that are not shown, after "Open Agenda" and a
    // " · " (no "+", one link row: «N more», the board card's form).
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
    expect(screen.getByText("· 3 more")).toHaveClass("work-compact-more");
    expect(screen.queryByText(/\+3/)).toBeNull();
    const open = container.querySelector("button.work-compact-action");
    expect(open).toHaveClass("sk-btn--open");
    expect(
      open?.querySelector(".work-compact-open-text .work-compact-more"),
    ).not.toBeNull();
  });

  it("says in one line how many records of both groups the card leaves out, in Swedish too", () => {
    const records: WorkItemRecord[] = [
      ...["Idag ett", "Idag två"].map((title, index) => ({
        kind: "task" as const,
        id: `019f0000-0000-7000-8000-0000000000${index}1`,
        title,
        status: "todo",
        due_at: "2026-10-25T15:00:00Z",
        agenda_group: "today" as const,
      })),
      ...["Sen ett", "Sen två"].map((title, index) => ({
        kind: "task" as const,
        id: `019f0000-0000-7000-8000-0000000000${index}2`,
        title,
        status: "todo",
        due_at: "2026-10-20T09:00:00Z",
        agenda_group: "overdue" as const,
      })),
    ];
    const { container } = render(
      <AgendaSummary
        page={{ items: records, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    // The three rows are the first today record and the two overdue ones; the second today record is left out.
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
    expect(screen.getByText("· 1 fler")).toHaveClass("work-compact-more");
    expect(screen.queryByText(/fler försenade|fler idag/)).toBeNull();
  });

  it("adds the left-out rows of both groups into one count, and the labels give no text for zero", () => {
    const records: WorkItemRecord[] = [
      ...[1, 2, 3, 4].map((n) => ({
        kind: "task" as const,
        id: `019f0000-0000-7000-8000-0000000000${n}1`,
        title: `Idag ${n}`,
        status: "todo",
        due_at: "2026-10-25T15:00:00Z",
        agenda_group: "today" as const,
      })),
      ...[1, 2].map((n) => ({
        kind: "task" as const,
        id: `019f0000-0000-7000-8000-0000000000${n}2`,
        title: `Sen ${n}`,
        status: "todo",
        due_at: "2026-10-20T09:00:00Z",
        agenda_group: "overdue" as const,
      })),
    ];
    const { container } = render(
      <AgendaSummary
        page={{ items: records, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    // Three rows shown: one today record and the two overdue ones are left out, 3 in all.
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
    expect(screen.getByText("· 3 more")).toHaveClass("work-compact-more");
    expect(inlineSummaryLabelsEn.agendaHidden(3)).toBe("3 more");
    expect(inlineSummaryLabelsSv.agendaHidden(3)).toBe("3 fler");
    expect(inlineSummaryLabelsEn.agendaHidden(0)).toBe("");
    expect(inlineSummaryLabelsSv.agendaHidden(0)).toBe("");
    expect(inlineSummaryLabelsEn.openAgenda).toBe("Open Agenda");
    expect(inlineSummaryLabelsSv.openAgenda).toBe("Öppna Agenda");
  });

  it("says nothing more under the rows when the card shows every row of the page", () => {
    render(
      <AgendaSummary
        page={{
          items: agendaItems.filter((item) => item.agenda_group !== "upcoming"),
          next_cursor: null,
        }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(/· \d+ more/)).toBeNull();
    expect(
      screen.getByRole("button", { name: "Open Agenda" }),
    ).toBeInTheDocument();
  });

  it("counts the foot against every row of the page the Agenda lists: 10 rows, 3 shown, '7 more' / '7 fler'", () => {
    const rows: WorkItemRecord[] = Array.from({ length: 10 }, (_, index) => ({
      kind: "task" as const,
      id: `019f0000-0000-7000-8000-0000000000${index}3`,
      title: `Uppgift ${index + 1}`,
      status: "todo",
      due_at:
        index < 2
          ? "2026-10-20T09:00:00Z"
          : index < 4
            ? "2026-10-25T15:00:00Z"
            : "2026-11-02T09:00:00Z",
      agenda_group: index < 2 ? "overdue" : index < 4 ? "today" : "upcoming",
    }));
    const { container, unmount } = render(
      <AgendaSummary
        page={{ items: rows, next_cursor: null }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(container.querySelectorAll(".work-compact-row")).toHaveLength(3);
    expect(screen.getByText("· 7 more")).toHaveClass("work-compact-more");
    unmount();
    render(
      <AgendaSummary
        page={{ items: rows, next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("· 7 fler")).toHaveClass("work-compact-more");
  });

  it("does not claim an exact count in the foot while another page exists: '7+ more' / '7+ fler'", () => {
    const rows: WorkItemRecord[] = Array.from({ length: 10 }, (_, index) => ({
      kind: "task" as const,
      id: `019f0000-0000-7000-8000-0000000000${index}4`,
      title: `Uppgift ${index + 1}`,
      status: "todo",
      due_at:
        index < 2
          ? "2026-10-20T09:00:00Z"
          : index < 4
            ? "2026-10-25T15:00:00Z"
            : "2026-11-02T09:00:00Z",
      agenda_group: index < 2 ? "overdue" : index < 4 ? "today" : "upcoming",
    }));
    const { unmount } = render(
      <AgendaSummary
        page={{ items: rows, next_cursor: "next" }}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("· 7+ more")).toHaveClass("work-compact-more");
    unmount();
    render(
      <AgendaSummary
        page={{ items: rows, next_cursor: "next" }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText("· 7+ fler")).toHaveClass("work-compact-more");
    expect(inlineSummaryLabelsEn.agendaHidden(7, true)).toBe("7+ more");
    expect(inlineSummaryLabelsSv.agendaHidden(7, true)).toBe("7+ fler");
    expect(inlineSummaryLabelsSv.agendaHidden(0, true)).toBe("");
  });
});
