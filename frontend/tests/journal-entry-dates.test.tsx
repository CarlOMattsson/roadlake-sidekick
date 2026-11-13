import { render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";
import { ProposalCheck } from "@/features/journal-app/draft-review-parts/proposal-check";
import { EntryRow } from "@/features/journal-app/entry-row";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { ownerToday } from "@/features/mcp-apps/app-timezone";
import {
  createProposal,
  entry,
  entryId,
  source,
  sourceId,
  transportMock,
} from "./helpers/journal-app-fixtures";

// The year is shown only for a day that is not in the owner's current year. The dates are built from the clock
// the app reads, so the test holds in any year.
const thisYear = Number(ownerToday(undefined).slice(0, 4));
const thisYearDay = `${thisYear}-01-02`;
const earlierDay = `${thisYear - 1}-05-09`;

function renderRow(journalDate: string, labels = journalEn) {
  render(
    <ul>
      <EntryRow
        dated
        labels={labels}
        entry={{
          id: "e1",
          source_id: "s1",
          title: "A row",
          summary: null,
          occurred_at: null,
          journal_date: journalDate,
        }}
      />
    </ul>,
  );
  return document.querySelector(".journal-entry-meta")?.textContent;
}

describe("the day on a dated row", () => {
  it("leaves the year out for a day in the current year", () => {
    expect(renderRow(thisYearDay)).toBe("2 Jan");
  });

  it("adds the year for an earlier year, in both languages", () => {
    expect(renderRow(earlierDay)).toBe(`9 May ${thisYear - 1}`);
  });

  it("adds the year in Swedish too", () => {
    expect(renderRow(earlierDay, journalSv)).toBe(`9 maj ${thisYear - 1}`);
  });
});

describe("the day on the entry view", () => {
  async function dateLine(journalDate: string) {
    const transport = transportMock({
      getEntry: vi.fn(() =>
        Promise.resolve({
          entry: { ...entry, journal_date: journalDate, occurred_at: null },
        }),
      ),
    });
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "entry", id: entryId }}
        labels={journalEn}
      />,
    );
    await screen.findByRole("heading", { level: 2, name: entry.title });
    return screen.getByText(/^\d+ \w+( \d{4})?$/).textContent;
  }

  it("leaves the year out for a day in the current year", async () => {
    expect(await dateLine(thisYearDay)).toBe("2 Jan");
  });

  it("adds the year for an earlier year", async () => {
    expect(await dateLine(earlierDay)).toBe(`9 May ${thisYear - 1}`);
  });
});

describe("the day on the original text view", () => {
  async function sourceLine(journalDate: string) {
    const transport = transportMock({
      getSource: vi.fn(() =>
        Promise.resolve({ source: { ...source, journal_date: journalDate } }),
      ),
    });
    render(
      <JournalView
        transport={transport}
        initial={{ kind: "source", id: sourceId }}
        labels={journalEn}
      />,
    );
    return (await screen.findByText(/^.+ · \d+ \w+( \d{4})?$/)).textContent;
  }

  it("leaves the year out for a day in the current year", async () => {
    expect(await sourceLine(thisYearDay)).toMatch(/ · 2 Jan$/);
  });

  it("adds the year for an earlier year", async () => {
    expect(await sourceLine(earlierDay)).toMatch(
      new RegExp(` · 9 May ${thisYear - 1}$`),
    );
  });
});

describe("the language on the original text view", () => {
  async function languageLine(labels = journalEn) {
    render(
      <JournalView
        transport={transportMock()}
        initial={{ kind: "source", id: sourceId }}
        labels={labels}
      />,
    );
    return (await screen.findByText(new RegExp(`^${labels.language}: `)))
      .textContent;
  }

  it("names the language in English, not by its code", async () => {
    expect(await languageLine()).toBe("Language: Swedish");
  });

  it("names the language in Swedish, in lower case", async () => {
    expect(await languageLine(journalSv)).toBe("Språk: svenska");
  });
});

describe("the due date of a task proposal in a draft", () => {
  function dueLine(dueAt: string, labels = journalEn) {
    render(
      <ProposalCheck
        proposal={{ ...createProposal, description: null, due_at: dueAt }}
        taskLabel={() => ""}
        known
        checked={false}
        declined={false}
        disabled={false}
        onChange={() => undefined}
        onDeclinedChange={() => undefined}
        labels={labels}
      />,
    );
    return screen.getByText(new RegExp(`${labels.newDue}: `)).textContent;
  }

  it("leaves the year out for a date in the current year, as the rest of the journal does", () => {
    expect(dueLine(`${thisYear}-01-02T09:00:00Z`)).toMatch(/Due: 2 Jan$/);
  });

  it("adds the year for another year, and writes the Swedish month without a period", () => {
    expect(dueLine(`${thisYear + 1}-11-05`, journalSv)).toMatch(
      new RegExp(`Förfaller: 5 nov ${thisYear + 1}$`),
    );
  });
});
