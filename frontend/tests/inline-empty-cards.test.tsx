import {
  boardLabelsEn,
  boardLabelsSv,
} from "@/features/work-app/board/board-labels";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { DayGlance } from "@/features/journal-app/day-glance";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type { JournalDay } from "@/features/journal-app/transport";
import { RoomMessageContext } from "@/features/mcp-apps/ui/room-context";
import { BoardSummary } from "@/features/work-app/board/board-summary";
import {
  AgendaSummary,
  ContactsSummary,
  HierarchySummary,
} from "@/features/work-app/inline/inline-summary";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import type { WorkBoardPage } from "@/features/work-app/transport/transport";

// An empty inline card is the same in every room: the eyebrow, the room's sentence, the example to say to Claude and
// the room's open link. No counts of zero and no "Show all" when there is nothing to show.

const noCount = /^0\b|\b0 (open|projects|contacts|öppna|projekt|kontakter)/;

describe("empty Agenda card", () => {
  it("shows the sentence, the hint, the example and Open Agenda, with no counts", async () => {
    const user = userEvent.setup();
    const send = vi.fn(() => Promise.resolve(true));
    const onOpen = vi.fn();
    const { container } = render(
      <RoomMessageContext.Provider value={send}>
        <AgendaSummary
          page={{ items: [], next_cursor: null }}
          labels={inlineSummaryLabelsEn}
          onOpen={onOpen}
        />
      </RoomMessageContext.Provider>,
    );
    expect(screen.getByText(workEn.agendaEmpty)).toBeVisible();
    expect(screen.getByText(workEn.agendaEmptyHint)).toBeVisible();
    expect(container.textContent).not.toMatch(noCount);
    await user.click(
      screen.getByRole("button", { name: new RegExp(workEn.workEmptyAsk) }),
    );
    expect(send).toHaveBeenCalledWith(workEn.workEmptyAsk);
    await user.click(
      screen.getByRole("button", {
        name: inlineSummaryLabelsEn.openAgenda,
      }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("shows the example as text where the host offers no messages", () => {
    render(
      <AgendaSummary
        page={{ items: [], next_cursor: null }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText(workSv.agendaEmpty)).toBeVisible();
    expect(screen.getByText(`”${workSv.workEmptyAsk}”`)).toBeVisible();
    expect(screen.getByText("Be Claude i Claude-appen:")).toBeVisible();
  });
});

describe("empty Status card", () => {
  const empty: WorkBoardPage = { columns: {}, next_cursor: null };

  it("shows the sentence, the example and Open Status, with no zero counts or bar", async () => {
    const user = userEvent.setup();
    const send = vi.fn(() => Promise.resolve(true));
    const onOpen = vi.fn();
    const { container } = render(
      <RoomMessageContext.Provider value={send}>
        <BoardSummary page={empty} labels={workSv} onOpen={onOpen} />
      </RoomMessageContext.Provider>,
    );
    expect(screen.getByText(boardLabelsSv.empty)).toBeVisible();
    expect(screen.getByText(boardLabelsSv.emptyHint)).toBeVisible();
    expect(container.textContent).not.toMatch(noCount);
    expect(screen.queryByRole("img")).toBeNull();
    await user.click(screen.getByRole("button", { name: /Påminn mig/ }));
    expect(send).toHaveBeenCalledWith(workSv.workEmptyAsk);
    await user.click(
      screen.getByRole("button", { name: new RegExp(boardLabelsSv.openBoard) }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("keeps the counts once a Task exists", () => {
    render(
      <BoardSummary
        page={{
          columns: {
            todo: [
              {
                kind: "task",
                id: "t1",
                title: "Ring Anna",
                status: "todo",
                due_at: null,
                version: 1,
              },
            ],
          },
          next_cursor: null,
        }}
        labels={workEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.queryByText(boardLabelsEn.empty)).toBeNull();
  });
});

describe("empty Projects card", () => {
  it("shows the sentence, the example and Open Projects, with no zero counts and no Show all", async () => {
    const user = userEvent.setup();
    const send = vi.fn(() => Promise.resolve(true));
    const onOpen = vi.fn();
    const { container } = render(
      <RoomMessageContext.Provider value={send}>
        <HierarchySummary
          frame={{ kind: "hierarchy", nodes: [], truncated: false }}
          labels={inlineSummaryLabelsEn}
          onOpen={onOpen}
        />
      </RoomMessageContext.Provider>,
    );
    expect(screen.getByText(workEn.hierarchyEmpty)).toBeVisible();
    expect(container.textContent).not.toMatch(noCount);
    expect(
      screen.queryByRole("button", { name: inlineSummaryLabelsEn.showAll }),
    ).toBeNull();
    await user.click(
      screen.getByRole("button", {
        name: new RegExp(inlineSummaryLabelsEn.blank.hierarchy.example),
      }),
    );
    expect(send).toHaveBeenCalledWith(
      inlineSummaryLabelsEn.blank.hierarchy.example,
    );
    await user.click(
      screen.getByRole("button", {
        name: inlineSummaryLabelsEn.openHierarchy,
      }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });
});

describe("empty Contacts card", () => {
  it("shows the sentence, the hint, the example and Open contacts, with no zero count", async () => {
    const user = userEvent.setup();
    const send = vi.fn(() => Promise.resolve(true));
    const onOpen = vi.fn();
    const { container } = render(
      <RoomMessageContext.Provider value={send}>
        <ContactsSummary
          count={0}
          more={false}
          labels={inlineSummaryLabelsSv}
          onOpen={onOpen}
        />
      </RoomMessageContext.Provider>,
    );
    expect(screen.getByText(workSv.noAnyContacts)).toBeVisible();
    expect(
      screen.getByText(inlineSummaryLabelsSv.blank.contacts.hint),
    ).toBeVisible();
    expect(container.textContent).not.toMatch(noCount);
    await user.click(screen.getByRole("button", { name: /Spara Anna/ }));
    expect(send).toHaveBeenCalledWith(
      inlineSummaryLabelsSv.blank.contacts.example,
    );
    await user.click(
      screen.getByRole("button", {
        name: inlineSummaryLabelsSv.openContacts,
      }),
    );
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("says a search found nothing, without an example, and still opens the room", () => {
    render(
      <ContactsSummary
        count={0}
        more={false}
        query="Zorro"
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(screen.getByText(workEn.noContactMatches("Zorro"))).toBeVisible();
    expect(screen.queryByText(/Tell Claude|Ask Claude/)).toBeNull();
    expect(
      screen.getByRole("button", { name: inlineSummaryLabelsEn.openContacts }),
    ).toBeVisible();
  });
});

describe("cards that have more to open", () => {
  it("name the view and what it holds beyond the card, not a bare Show all", () => {
    render(
      <ContactsSummary
        count={5}
        more={false}
        contacts={[1, 2, 3, 4, 5].map((n) => ({ id: `c${n}`, name: `C${n}` }))}
        labels={inlineSummaryLabelsEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /^Open contacts\W+2 more$/,
      }),
    ).toBeVisible();
  });

  it("show the Projects beyond the three listed", () => {
    render(
      <HierarchySummary
        frame={{
          kind: "hierarchy",
          nodes: [1, 2, 3, 4].map((n) => ({
            kind: "project" as const,
            id: `p${n}`,
            parent_id: null,
            title: `P${n}`,
          })),
          truncated: false,
        }}
        labels={inlineSummaryLabelsSv}
        onOpen={vi.fn()}
      />,
    );
    expect(
      screen.getByRole("button", {
        name: /^Öppna Projekt\W+1 fler$/,
      }),
    ).toBeVisible();
  });
});

describe("empty Journal day glance", () => {
  const emptyDay: JournalDay = {
    journal_date: "2026-10-24",
    entries: [],
    next_cursor: null,
    summary: {
      journal_date: "2026-10-24",
      exists: false,
      status: "current",
      content: null,
    },
  };

  it("shows the sentence, the example for Claude and Open, with no count of zero entries", async () => {
    const user = userEvent.setup();
    const onTellClaude = vi.fn();
    const onOpen = vi.fn();
    const { container } = render(
      <DayGlance
        day={emptyDay}
        today="2026-10-24"
        labels={journalEn}
        onOpen={onOpen}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
        onTellClaude={onTellClaude}
      />,
    );
    expect(screen.getByText(journalEn.noEntriesToday)).toBeVisible();
    expect(container.textContent).not.toMatch(/\b0 entries/);
    await user.click(
      screen.getByRole("button", {
        name: new RegExp(journalEn.tellClaudeMessage.slice(0, 20)),
      }),
    );
    expect(onTellClaude).toHaveBeenCalledWith(journalEn.tellClaudeMessage);
    await user.click(screen.getByRole("button", { name: journalEn.cardOpen }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("names an earlier day in the example, and shows it as text without a message function", () => {
    render(
      <DayGlance
        day={emptyDay}
        today="2026-10-25"
        labels={journalSv}
        onOpen={vi.fn()}
        onOpenEntry={vi.fn()}
        onReviewDrafts={vi.fn()}
      />,
    );
    expect(screen.getByText(journalSv.noEntries)).toBeVisible();
    expect(screen.getByText(/lördag 24 oktober/)).toBeVisible();
    expect(screen.getByText("Be Claude i Claude-appen:")).toBeVisible();
  });
});
