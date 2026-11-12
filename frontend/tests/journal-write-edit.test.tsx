import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import {
  createJournalTransport,
  type JournalDay,
  type JournalEntry,
  type JournalFrame,
  type JournalTransport,
} from "@/features/journal-app/transport";

const entryId = "019f0000-0000-7000-8000-0000000000e1";

const entry: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000s1",
  journal_date: "2026-10-24",
  occurred_at: null,
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [{ kind: "commitment", text: "Skicka offerten." }],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  archived: false,
  version: 3,
};
const saved: JournalEntry = { ...entry, title: "Ny titel", version: 4 };

function emptyDay(date: string): JournalDay {
  return {
    journal_date: date,
    entries: [],
    next_cursor: null,
    summary: { journal_date: date, exists: false, status: null, content: null },
  };
}
const dayRoot: JournalFrame = { kind: "day", page: emptyDay("2026-10-24") };
const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function transport(extra: Partial<JournalTransport>): JournalTransport {
  return {
    getDay: vi.fn().mockResolvedValue(emptyDay("2026-10-24")),
    getEntry: vi.fn().mockResolvedValue({ entry }),
    getSource: vi.fn(),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
    ...extra,
  } as unknown as JournalTransport;
}

describe("transport arguments", () => {
  it("maps the three writes to the tools with the key and version", async () => {
    const call = vi.fn().mockResolvedValue({ entry });
    const t = createJournalTransport(call);
    await t.writeEntry!(
      { journal_date: "2026-10-24", title: "A", source_text: "B" },
      "key-00000001",
    );
    await t.updateEntry!(
      entryId,
      3,
      { title: "T", summary: null, key_points: [] },
      "key-00000002",
    );
    await t.appendEntryText!(entryId, 3, "Mer", "key-00000003");
    expect(call.mock.calls).toEqual([
      [
        "write_journal_entry",
        {
          journal_date: "2026-10-24",
          title: "A",
          source_text: "B",
          idempotency_key: "key-00000001",
        },
      ],
      [
        "update_journal_entry",
        {
          entry_id: entryId,
          expected_version: 3,
          idempotency_key: "key-00000002",
          title: "T",
          summary: null,
          key_points: [],
        },
      ],
      [
        "update_journal_entry",
        {
          entry_id: entryId,
          expected_version: 3,
          idempotency_key: "key-00000003",
          append_text: "Mer",
        },
      ],
    ]);
  });
});

describe("writing a new entry", () => {
  it("blocks an empty title and sends the day, the words and a key", async () => {
    const user = userEvent.setup();
    const writeEntry = vi
      .fn<NonNullable<JournalTransport["writeEntry"]>>()
      .mockResolvedValue({ entry });
    const getDay = vi.fn().mockResolvedValue(emptyDay("2026-10-24"));
    render(
      <JournalView
        transport={transport({ writeEntry, getDay })}
        initial={dayRoot}
        labels={journalSv}
      />,
    );
    await user.click(screen.getByRole("button", { name: "Ny anteckning" }));
    const form = screen.getByRole("group", { name: "Ny anteckning" });
    await user.type(
      within(form).getByLabelText(journalSv.entryTextLabel),
      "Dagens text",
    );
    await user.click(
      within(form).getByRole("button", { name: journalSv.saveEntry }),
    );
    expect(await within(form).findByRole("alert")).toHaveTextContent(
      journalSv.titleRequired,
    );
    expect(writeEntry).not.toHaveBeenCalled();

    await user.type(
      within(form).getByLabelText(journalSv.titleLabel),
      "Rubrik",
    );
    await user.click(
      within(form).getByRole("button", { name: journalSv.saveEntry }),
    );
    await waitFor(() => expect(writeEntry).toHaveBeenCalledTimes(1));
    const [input, key] = writeEntry.mock.calls[0]!;
    expect(input).toEqual({
      journal_date: "2026-10-24",
      title: "Rubrik",
      source_text: "Dagens text",
      occurred_at: new Date(2026, 9, 24, 12).toISOString(),
    });
    expect(key.length).toBeGreaterThanOrEqual(8);
    expect(await screen.findByText(journalSv.entryCreated)).toBeVisible();
    expect(getDay).toHaveBeenCalledWith("2026-10-24");
  });

  it("keeps the text and reuses the key when the same attempt is retried", async () => {
    const user = userEvent.setup();
    const writeEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValue({ entry });
    render(
      <JournalView
        transport={transport({ writeEntry })}
        initial={dayRoot}
        labels={journalEn}
      />,
    );
    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    await user.type(screen.getByLabelText(journalEn.titleLabel), "Title");
    await user.type(screen.getByLabelText(journalEn.entryTextLabel), "Words");
    await user.click(screen.getByRole("button", { name: journalEn.saveEntry }));
    expect(
      await screen.findByText(journalEn.entryCreateFailed),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(journalEn.entryTextLabel)).toHaveValue(
      "Words",
    );
    await user.click(screen.getByRole("button", { name: journalEn.saveEntry }));
    await waitFor(() => expect(writeEntry).toHaveBeenCalledTimes(2));
    expect(writeEntry.mock.calls[1]![1]).toBe(writeEntry.mock.calls[0]![1]);
  });

  it("closes at once without text and asks first with unsaved text", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport({ writeEntry: vi.fn() })}
        initial={dayRoot}
        labels={journalEn}
      />,
    );
    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    await user.click(screen.getByRole("button", { name: journalEn.cancel }));
    expect(screen.queryByLabelText(journalEn.entryTextLabel)).toBeNull();

    await user.click(screen.getByRole("button", { name: journalEn.addEntry }));
    await user.type(screen.getByLabelText(journalEn.entryTextLabel), "Keep");
    await user.click(screen.getByRole("button", { name: journalEn.cancel }));
    expect(screen.getByText(journalEn.discardAsk)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: journalEn.keepWriting }),
    );
    expect(screen.getByLabelText(journalEn.entryTextLabel)).toHaveValue("Keep");
  });
});

describe("changing an entry by hand", () => {
  it("sends the version and the kept fields, leaving the original alone", async () => {
    const user = userEvent.setup();
    const updateEntry = vi
      .fn<NonNullable<JournalTransport["updateEntry"]>>()
      .mockResolvedValue({ entry: saved });
    render(
      <JournalView
        transport={transport({ updateEntry })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalSv.editEntry }),
    );
    const title = screen.getByLabelText(journalSv.titleLabel);
    await user.clear(title);
    await user.type(title, "Ny titel");
    await user.click(
      screen.getByRole("button", { name: journalSv.saveChanges }),
    );
    await waitFor(() => expect(updateEntry).toHaveBeenCalledTimes(1));
    const [id, version, fields, key] = updateEntry.mock.calls[0]!;
    expect(id).toBe(entryId);
    expect(version).toBe(3);
    expect(fields).toEqual({
      title: "Ny titel",
      summary: entry.summary,
      key_points: entry.key_points,
    });
    expect(key.length).toBeGreaterThanOrEqual(8);
    expect(await screen.findByText(journalSv.entryUpdated)).toBeVisible();
    expect(screen.getByRole("heading", { name: "Ny titel" })).toBeVisible();
  });

  it("writes nothing when nothing changed", async () => {
    const user = userEvent.setup();
    const updateEntry = vi.fn();
    render(
      <JournalView
        transport={transport({ updateEntry })}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    );
    await user.click(
      screen.getByRole("button", { name: journalEn.saveChanges }),
    );
    expect(updateEntry).not.toHaveBeenCalled();
    expect(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    ).toBeVisible();
  });

  it("keeps what was written on a stale version, reloads and saves at the new version", async () => {
    const user = userEvent.setup();
    const updateEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("conflict"))
      .mockResolvedValue({ entry: { ...saved, version: 6 } });
    const newer: JournalEntry = {
      ...entry,
      summary: "Annan sammanfattning.",
      version: 5,
    };
    const getEntry = vi
      .fn()
      .mockResolvedValueOnce({ entry })
      .mockResolvedValue({ entry: newer });
    render(
      <JournalView
        transport={transport({ updateEntry, getEntry })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalSv.editEntry }),
    );
    const title = screen.getByLabelText(journalSv.titleLabel);
    await user.clear(title);
    await user.type(title, "Ny titel");
    await user.click(
      screen.getByRole("button", { name: journalSv.saveChanges }),
    );
    expect(
      await screen.findByText(journalSv.entryEditConflict),
    ).toBeInTheDocument();
    await waitFor(() => expect(getEntry).toHaveBeenCalledTimes(2));
    expect(screen.getByLabelText(journalSv.titleLabel)).toHaveValue("Ny titel");
    expect(screen.getByLabelText(journalSv.summaryLabel)).toHaveValue(
      "Annan sammanfattning.",
    );

    await user.click(
      screen.getByRole("button", { name: journalSv.saveChanges }),
    );
    await waitFor(() => expect(updateEntry).toHaveBeenCalledTimes(2));
    expect(updateEntry.mock.calls[1]![1]).toBe(5);
    expect(updateEntry.mock.calls[1]![3]).not.toBe(
      updateEntry.mock.calls[0]![3],
    );
  });

  it("adds text with append_text and keeps the text on a stale version", async () => {
    const user = userEvent.setup();
    const appendEntryText = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("conflict"))
      .mockResolvedValue({ entry: { ...entry, version: 6 } });
    const getEntry = vi
      .fn()
      .mockResolvedValueOnce({ entry })
      .mockResolvedValue({ entry: { ...entry, version: 5 } });
    render(
      <JournalView
        transport={transport({ appendEntryText, getEntry })}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalEn.appendText }),
    );
    await user.type(screen.getByLabelText(journalEn.appendTextLabel), "More");
    await user.click(
      screen.getByRole("button", { name: journalEn.appendTextSave }),
    );
    expect(
      await screen.findByText(journalEn.entryEditConflict),
    ).toBeInTheDocument();
    expect(screen.getByLabelText(journalEn.appendTextLabel)).toHaveValue(
      "More",
    );
    await waitFor(() => expect(getEntry).toHaveBeenCalledTimes(2));
    await user.click(
      screen.getByRole("button", { name: journalEn.appendTextSave }),
    );
    await waitFor(() => expect(appendEntryText).toHaveBeenCalledTimes(2));
    expect(appendEntryText.mock.calls[1]!.slice(0, 3)).toEqual([
      entryId,
      5,
      "More",
    ]);
    expect(await screen.findByText(journalEn.entryTextAdded)).toBeVisible();
  });

  it("asks before dropping changed text", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport({ updateEntry: vi.fn() })}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    );
    await user.type(screen.getByLabelText(journalEn.titleLabel), "!");
    await user.click(screen.getByRole("button", { name: journalEn.cancel }));
    expect(screen.getByText(journalEn.discardAsk)).toBeInTheDocument();
    await user.click(
      screen.getByRole("button", { name: journalEn.discardYes }),
    );
    expect(screen.queryByLabelText(journalEn.titleLabel)).toBeNull();
  });
});
