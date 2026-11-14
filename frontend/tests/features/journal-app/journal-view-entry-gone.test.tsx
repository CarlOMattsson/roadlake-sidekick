import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import type {
  JournalEntry,
  JournalFrame,
  JournalTransport,
} from "@/features/journal-app/transport";

const entryId = "019f0000-0000-7000-8000-0000000000e1";
const sourceId = "019f0000-0000-7000-8000-0000000000s1";

const entry: JournalEntry = {
  id: entryId,
  source_id: sourceId,
  journal_date: "2026-10-24",
  occurred_at: null,
  title: "Mötet om offerten",
  summary: null,
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 1,
};

/** An entry root: the view reads the entry itself through getEntry. */
const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function transportWith(
  getEntry: JournalTransport["getEntry"],
): JournalTransport {
  return {
    getDay: vi.fn(),
    getEntry,
    getSource: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
  };
}

describe("journal entry that no longer exists", () => {
  it("shows the calm line without retry when the read says not_found", async () => {
    const getEntry = vi.fn().mockRejectedValue(new HostToolError("not_found"));
    render(
      <JournalView
        transport={transportWith(getEntry)}
        initial={entryRoot}
        labels={journalEn}
      />,
    );

    expect(await screen.findByText(journalEn.entryGone)).toBeInTheDocument();
    expect(screen.queryByRole("alert")).not.toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalEn.retry }),
    ).not.toBeInTheDocument();
  });

  it("shows the Swedish line for the Swedish labels", async () => {
    const getEntry = vi.fn().mockRejectedValue(new HostToolError("not_found"));
    render(
      <JournalView
        transport={transportWith(getEntry)}
        initial={entryRoot}
        labels={journalSv}
      />,
    );

    expect(
      await screen.findByText("Anteckningen finns inte längre"),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: journalSv.retry }),
    ).not.toBeInTheDocument();
  });

  it("keeps the retry notice for a transient failure", async () => {
    const user = userEvent.setup();
    const getEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValue({ entry });
    render(
      <JournalView
        transport={transportWith(getEntry)}
        initial={entryRoot}
        labels={journalEn}
      />,
    );

    const retry = await screen.findByRole("button", { name: journalEn.retry });
    expect(screen.queryByText(journalEn.entryGone)).not.toBeInTheDocument();
    await user.click(retry);
    expect(
      await screen.findByRole("heading", { name: "Mötet om offerten" }),
    ).toBeInTheDocument();
    expect(getEntry).toHaveBeenCalledTimes(2);
  });
});
