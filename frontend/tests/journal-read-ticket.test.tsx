import { act, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalFrame,
  JournalTransport,
} from "@/features/journal-app/transport";

/*
 * A read of the entry that started before a successful link change must not put the older entry
 * (with the link still on it) back when it answers late.
 */

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const contactAnna = "019f0000-0000-7000-8000-0000000000c1";
const projectOffer = "019f0000-0000-7000-8000-0000000000a1";

const before: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000b1",
  journal_date: "2026-10-24",
  occurred_at: null,
  title: "Mötet om offerten",
  summary: null,
  key_points: [],
  project_ids: [projectOffer],
  task_ids: [],
  contact_ids: [contactAnna],
  links: [
    { kind: "project", id: projectOffer, label: "Offert Norr" },
    { kind: "contact", id: contactAnna, label: "Anna Berg" },
  ],
  tags: [],
  archived: false,
  version: 3,
};
const after: JournalEntry = {
  ...before,
  contact_ids: [],
  links: [{ kind: "project", id: projectOffer, label: "Offert Norr" }],
  version: 4,
};

const root: JournalFrame = { kind: "entry", id: entryId };

describe("Journal entry: a late read does not undo a link change", () => {
  it("keeps the link removed when an older read answers after the write", async () => {
    const user = userEvent.setup();
    let resolveLate!: (value: { entry: JournalEntry }) => void;
    const late = new Promise<{ entry: JournalEntry }>((done) => {
      resolveLate = done;
    });
    const getEntry = vi
      .fn()
      .mockResolvedValueOnce({ entry: before })
      .mockReturnValueOnce(late);
    const updateEntryLinks = vi.fn().mockResolvedValue({ entry: after });
    const transport = {
      getEntry,
      updateEntryLinks,
      updateEntry: vi.fn(),
    } as unknown as JournalTransport;
    const view = (refreshKey: number) => (
      <JournalView
        transport={transport}
        initial={root}
        labels={journalEn}
        refreshKey={refreshKey}
      />
    );
    const { rerender } = render(view(0));
    await screen.findByText("Anna Berg");

    // Read A: a refresh asks again and hangs.
    rerender(view(1));
    expect(getEntry).toHaveBeenCalledTimes(2);

    // Write B: the link to Anna is removed. The × only shows while the entry is being changed.
    await user.click(screen.getByRole("button", { name: journalEn.editEntry }));
    await user.click(
      screen.getByRole("button", {
        name: journalEn.linkRemove("Anna Berg"),
      }),
    );
    await user.click(
      screen.getByRole("button", { name: journalEn.linkRemoveConfirm }),
    );
    expect(
      await screen.findByText(journalEn.linkRemoved("Anna Berg")),
    ).toBeInTheDocument();
    expect(updateEntryLinks).toHaveBeenCalledTimes(1);

    // A answers late with the older entry: Anna's link does not come back.
    await act(async () => {
      resolveLate({ entry: before });
      await late;
    });
    expect(
      screen.queryByRole("button", {
        name: journalEn.linkRemove("Anna Berg"),
      }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByText(journalEn.linkRemoved("Anna Berg")),
    ).toBeInTheDocument();
    expect(screen.getByText("Offert Norr")).toBeInTheDocument();
  });
});
