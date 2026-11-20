import { act, fireEvent, render, screen, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterEach, describe, expect, it, vi } from "vitest";
import { JournalView } from "@/features/journal-app/journal-view";
import {
  journalEn,
  journalSv,
  type JournalLabels,
} from "@/features/journal-app/labels";
import { receiptText } from "@/features/journal-app/receipt-text";
import type {
  JournalEntry,
  JournalFrame,
  JournalTransport,
} from "@/features/journal-app/transport";
import { RECEIPT_MS } from "@/features/mcp-apps/ui/receipt";

// The entry view confirms every change in one receipt bar (role=status, last in the view), never as a line in the
// content; it goes away by itself and with the entry. The transport is faked.
const entryId = "019f0000-0000-7000-8000-0000000000e1";
const entry: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: null,
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 3,
};
const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function transport(extra: Partial<JournalTransport> = {}): JournalTransport {
  return {
    getDay: vi.fn(),
    getEntry: vi.fn().mockResolvedValue({ entry }),
    getSource: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
    ...extra,
  };
}

afterEach(() => vi.useRealTimers());

/** Lets the pending answers and renders settle under fake timers (testing-library's own waiting would hang). */
async function settle(ms = 0) {
  await act(async () => {
    await vi.advanceTimersByTimeAsync(ms);
  });
}

const sets = [
  ["en", journalEn],
  ["sv", journalSv],
] as const;

describe.each(sets)(
  "the entry's receipt bar (%s)",
  (_name, t: JournalLabels) => {
    it("confirms a saved change in the status bar and takes it away by itself", async () => {
      vi.useFakeTimers();
      // userEvent waits on a real timer between steps; under fake timers the plain DOM events are used.
      const updateEntry = vi
        .fn<NonNullable<JournalTransport["updateEntry"]>>()
        .mockResolvedValue({
          entry: { ...entry, title: "Ny titel", version: 4 },
        });
      render(
        <JournalView
          transport={transport({ updateEntry })}
          initial={entryRoot}
          labels={t}
        />,
      );
      await settle();
      fireEvent.click(screen.getByRole("button", { name: t.editEntry }));
      // While the text is edited the "original saved" line is not there.
      expect(screen.queryByRole("button", { name: t.showOriginal })).toBeNull();
      // An input event, not a change event: Preact's onChange listens to input, React's to both.
      fireEvent.input(screen.getByLabelText(t.titleLabel), {
        target: { value: "Ny titel" },
      });
      fireEvent.click(screen.getByRole("button", { name: t.save }));

      await settle();
      const bar = screen.getByRole("status");
      expect(within(bar).getByText(receiptText(t.entryUpdated))).toBeVisible();
      // Not a line in the content: the receipt is the last child of the view.
      const article = bar.closest("article");
      expect(article?.lastElementChild).toBe(bar);
      // The original line is back once the form is closed.
      expect(
        screen.getByRole("button", { name: t.showOriginal }),
      ).toBeVisible();

      await settle(RECEIPT_MS + 100);
      expect(screen.queryByText(receiptText(t.entryUpdated))).toBeNull();
    });

    it("confirms a memory choice in the bar, and the marker is a chip", async () => {
      const user = userEvent.setup();
      const excludeEntryFromMemory = vi
        .fn()
        .mockResolvedValue({ changed: true });
      render(
        <JournalView
          transport={transport({
            excludeEntryFromMemory,
            trashEntry: vi.fn(),
            restoreEntry: vi.fn(),
          })}
          initial={entryRoot}
          labels={t}
        />,
      );
      await screen.findByRole("heading", { name: entry.title });
      await user.click(
        screen.getByRole("button", { name: t.entryMoreActions }),
      );
      await user.click(
        screen.getByRole("button", { name: t.entryKeepOutOfMemory }),
      );

      const bar = await screen.findByRole("status");
      expect(
        await within(bar).findByText(receiptText(t.entryKeptOutOfMemory)),
      ).toBeVisible();
      const chip = screen.getByText(t.entryOutOfMemory);
      expect(chip).toHaveClass("journal-memory-chip");
      expect(chip.closest("button")).toBeNull();
      expect(chip.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    });
  },
);
