import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JournalView } from "@/features/journal-app/journal-view";
import { EntryCard, summaryRest } from "@/features/journal-app/entry-card";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalFrame,
  JournalTransport,
} from "@/features/journal-app/transport";

describe("summaryRest", () => {
  it.each([
    ["Promenad", "Promenad runt sjön efter middagen, det hjälpte mot oron."],
    ["Möte", "Möte med Anna om offerten."],
    ["Möte", "Mötesanteckningar från dagen."],
    ["Möte", "Något helt annat."],
  ])(
    "keeps the whole summary when %s is only a word of the sentence",
    (title, summary) => {
      expect(summaryRest(title, summary)).toBe(summary);
    },
  );

  it.each([
    ["Möte", "Möte: vi enades om rabatten.", "vi enades om rabatten."],
    ["Möte", "Möte – vi enades om rabatten.", "vi enades om rabatten."],
    ["Möte", "Möte. Vi enades om rabatten.", "Vi enades om rabatten."],
    ["Möte", "möte — Vi enades.", "Vi enades."],
  ])(
    "cuts the title off %s when punctuation separates it",
    (title, summary, rest) => {
      expect(summaryRest(title, summary)).toBe(rest);
    },
  );

  it.each([
    ["Möte", "  möte "],
    ["Möte", "Möte:"],
    ["Möte", "Möte –"],
    ["Möte", null],
  ])(
    "shows nothing when the summary is only the title (%s, %s)",
    (title, summary) => {
      expect(summaryRest(title, summary)).toBeUndefined();
    },
  );
});

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const entry: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: null,
  title: "Kvällen",
  summary: "Jag var trött men glad.",
  summary_by: "you",
  memory_excluded: false,
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 1,
};
const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function transport(found: JournalEntry): JournalTransport {
  return {
    getDay: vi.fn(),
    getEntry: vi.fn().mockResolvedValue({ entry: found }),
    getSource: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
    updateEntry: vi.fn(),
    appendEntryText: vi.fn(),
  };
}

describe("an entry whose summary holds the owner's own words", () => {
  it.each([
    ["sv", journalSv],
    ["en", journalEn],
  ] as const)(
    "does not credit Claude in the entry view and labels the edit field as her text (%s)",
    async (_name, labels) => {
      const user = userEvent.setup();
      render(
        <JournalView
          transport={transport(entry)}
          initial={entryRoot}
          labels={labels}
        />,
      );
      await screen.findByRole("heading", { name: entry.title });
      expect(screen.getByText(labels.originalSavedNote)).toBeVisible();
      expect(screen.queryByText(labels.summarizedNote)).toBeNull();

      await user.click(screen.getByRole("button", { name: labels.editEntry }));
      expect(screen.getByLabelText(labels.entryTextLabel)).toHaveValue(
        entry.summary,
      );
      expect(screen.queryByLabelText(labels.summaryLabel)).toBeNull();
    },
  );

  it("still credits Claude and says Sammanfattning for a summary Claude wrote", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport({ ...entry, summary_by: null })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await screen.findByRole("heading", { name: entry.title });
    expect(screen.getByText(journalSv.summarizedNote)).toBeVisible();
    await user.click(screen.getByRole("button", { name: journalSv.editEntry }));
    expect(screen.getByLabelText(journalSv.summaryLabel)).toBeVisible();
  });

  it("leaves Sammanfattad av Claude out of the compact card's meta line", () => {
    render(
      <EntryCard
        entry={{
          id: entryId,
          title: entry.title,
          summary: entry.summary,
          summary_by: "you",
          contact_ids: [],
          task_ids: [],
        }}
        today="2026-10-24"
        labels={journalSv}
        onOpen={() => undefined}
      />,
    );
    expect(screen.queryByText(journalSv.cardSummarized)).toBeNull();
    expect(screen.getByText(journalSv.cardNoLinks)).toBeVisible();
  });

  it("says no links without 'yet' in both languages", () => {
    expect(journalSv.cardNoLinks).toBe("Inte kopplad till något");
    expect(journalEn.cardNoLinks).toBe("Not linked to anything");
  });
});
