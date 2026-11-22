import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { afterAll, beforeAll, describe, expect, it, vi } from "vitest";
import { entryTextOf } from "@/features/journal-app/entry-read";
import {
  entryReadEn,
  entryReadFor,
  entryReadSv,
} from "@/features/journal-app/entry-read-labels";
import { EntryTextForm } from "@/features/journal-app/entry-write";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalSource,
  JournalTransport,
} from "@/features/journal-app/transport";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";

// The days are named with their weekday and, outside this year, the year, so the clock the app reads is fixed.
const day = "2026-03-18"; // a Wednesday
const otherDay = "2026-03-10"; // a Tuesday

beforeAll(() => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(new Date("2026-11-20T12:00:00Z"));
});
afterAll(() => {
  vi.useRealTimers();
});
const firstId = "019f0000-0000-7000-8000-0000000000a1";
const secondId = "019f0000-0000-7000-8000-0000000000a2";
const thirdId = "019f0000-0000-7000-8000-0000000000a3";
const earlierId = "019f0000-0000-7000-8000-0000000000a0";
const ownText = "Vi gick längs vattnet.\n\nDet var ljust länge.";

function entryOf(
  id: string,
  title: string,
  extra: Partial<JournalEntry> = {},
): JournalEntry {
  return {
    id,
    source_id: `${id}-source`,
    journal_date: day,
    occurred_at: null,
    title,
    summary: "Kvällen blev lugn och ljus.",
    key_points: [],
    project_ids: [],
    task_ids: [],
    contact_ids: [],
    tags: [],
    archived: false,
    version: 1,
    ...extra,
  };
}

function sourceOf(
  type: JournalSource["source_type"],
  rawText: string | null,
): { source: JournalSource } {
  return {
    source: {
      id: "s",
      source_type: type,
      journal_date: day,
      occurred_at: null,
      source_recorded_at: null,
      language: "sv",
      created_at: `${day}T20:00:00Z`,
      raw_text: rawText,
    },
  };
}

function transportOf(
  entries: Record<string, JournalEntry>,
  source: (entry: JournalEntry) => { source: JournalSource } | undefined,
  extra: Partial<JournalTransport> = {},
): JournalTransport {
  return {
    getDay: vi.fn((journalDate: string) =>
      Promise.resolve({
        journal_date: journalDate,
        entries: Object.values(entries).filter(
          (entry) => entry.journal_date === journalDate,
        ),
        next_cursor: null,
        summary: {
          journal_date: journalDate,
          exists: false,
          status: null,
          content: null,
        },
      }),
    ),
    getEntry: vi.fn((id: string) => {
      const found = entries[id];
      return found
        ? Promise.resolve({ entry: found })
        : Promise.reject(new Error("-"));
    }),
    getSource: vi.fn((sourceId: string) => {
      const entry = Object.values(entries).find(
        (item) => item.source_id === sourceId,
      );
      const answer = entry ? source(entry) : undefined;
      return answer ? Promise.resolve(answer) : Promise.reject(new Error("-"));
    }),
    getDraft: vi.fn(),
    updateDraft: vi.fn(),
    rejectDraft: vi.fn(),
    finalizeDraft: vi.fn(),
    updateEntry: vi.fn(),
    appendEntryText: vi.fn(),
    ...extra,
  };
}

describe("the entry's text", () => {
  const base = {
    title: "Kvällen",
    summary: "Kvällen blev lugn och ljus.",
    summary_by: null,
  } as const;
  const ready = (type: JournalSource["source_type"], raw: string | null) =>
    ({
      phase: "ready",
      source: sourceOf(type, raw).source,
    }) as const;

  it("is the owner's original text, with Claude's summary kept apart", () => {
    expect(entryTextOf(base, ready("manual_text", ownText))).toEqual({
      main: ownText,
      waiting: false,
      summary: base.summary,
      original: false,
    });
  });

  it("offers the original under a transcription, and only then", () => {
    expect(entryTextOf(base, ready("transcript_text", ownText)).original).toBe(
      true,
    );
    expect(entryTextOf(base, ready("transcript_text", ownText)).original).toBe(
      true,
    );
    expect(entryTextOf(base, ready("manual_text", ownText)).original).toBe(
      false,
    );
  });

  it("is the owner's summary when it holds their words, and offers the original only if the words changed", () => {
    const own = { ...base, summary: ownText, summary_by: "you" } as const;
    expect(entryTextOf(own, ready("manual_text", ownText))).toMatchObject({
      main: ownText,
      original: false,
    });
    expect(entryTextOf(own, ready("manual_text", "Före ändringen."))).toEqual({
      main: ownText,
      waiting: false,
      summary: undefined,
      original: true,
    });
  });

  it("falls back to the summary when no original can be read, and offers the original to try again", () => {
    expect(entryTextOf(base, { phase: "none" })).toMatchObject({
      main: "Kvällen blev lugn och ljus.",
      original: false,
    });
    expect(entryTextOf(base, { phase: "failed" })).toMatchObject({
      main: "Kvällen blev lugn och ljus.",
      original: true,
    });
    expect(entryTextOf(base, ready("manual_text", null))).toMatchObject({
      main: "Kvällen blev lugn och ljus.",
      original: false,
    });
  });

  it("waits while the original is read, and does not say a summary that is the very text twice", () => {
    expect(entryTextOf(base, { phase: "loading" }).waiting).toBe(true);
    expect(
      entryTextOf({ ...base, summary: ownText }, ready("manual_text", ownText)),
    ).toMatchObject({ main: ownText, summary: undefined });
  });
});

describe("the entry view", () => {
  it("shows the owner's text before Claude's summary, which waits in a closed fold", async () => {
    const user = userEvent.setup();
    const entries = { [firstId]: entryOf(firstId, "Kvällen") };
    render(
      <JournalView
        transport={transportOf(entries, () => sourceOf("manual_text", ownText))}
        initial={{ kind: "entry", id: firstId }}
        labels={journalSv}
      />,
    );
    const text = await screen.findByText(/Vi gick längs vattnet/);
    // The paragraphs are kept: one block, written the way it was typed.
    expect(text.textContent).toBe(ownText);
    expect(text).toHaveClass("journal-entry-text");
    expect(screen.queryByText("Kvällen blev lugn och ljus.")).toBeNull();
    const fold = screen.getByRole("button", {
      name: entryReadSv.claudeSummary,
    });
    expect(fold).toHaveAttribute("aria-expanded", "false");
    // The text comes first in the page, the fold after it.
    expect(
      text.compareDocumentPosition(fold) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    await user.click(fold);
    expect(screen.getByText("Kvällen blev lugn och ljus.")).toBeVisible();
  });

  it("shows the summary as the text when there is no other text", async () => {
    const entries = {
      [firstId]: entryOf(firstId, "Kvällen", {
        summary: "Bara en sammanfattning.",
      }),
    };
    render(
      <JournalView
        transport={transportOf(entries, () => sourceOf("manual_text", null))}
        initial={{ kind: "entry", id: firstId }}
        labels={journalEn}
      />,
    );
    expect(await screen.findByText("Bara en sammanfattning.")).toHaveClass(
      "journal-entry-text",
    );
    expect(screen.queryByRole("button", { name: "Show original" })).toBeNull();
    expect(
      screen.queryByRole("button", { name: entryReadEn.claudeSummary }),
    ).toBeNull();
  });

  it("offers the original under a transcription and not under a text typed by hand", async () => {
    const entries = { [firstId]: entryOf(firstId, "Kvällen") };
    const { unmount } = render(
      <JournalView
        transport={transportOf(entries, () =>
          sourceOf("transcript_text", ownText),
        )}
        initial={{ kind: "entry", id: firstId }}
        labels={journalEn}
      />,
    );
    expect(
      await screen.findByRole("button", { name: "Show original" }),
    ).toBeVisible();
    unmount();
    render(
      <JournalView
        transport={transportOf(entries, () => sourceOf("manual_text", ownText))}
        initial={{ kind: "entry", id: firstId }}
        labels={journalEn}
      />,
    );
    await screen.findByText(/Vi gick längs vattnet/);
    await act(() => Promise.resolve());
    expect(screen.queryByRole("button", { name: "Show original" })).toBeNull();
    expect(screen.queryByText(journalEn.originalSavedNote)).toBeNull();
  });

  it("names the day with its weekday and the time, in both languages", async () => {
    const entries = {
      [firstId]: entryOf(firstId, "Kvällen", {
        occurred_at: `${day}T19:40:00Z`,
      }),
    };
    for (const labels of [journalSv, journalEn]) {
      const { unmount } = render(
        <JournalView
          transport={transportOf(entries, () => undefined)}
          initial={{ kind: "entry", id: firstId }}
          labels={labels}
        />,
      );
      await screen.findByRole("heading", { level: 2, name: "Kvällen" });
      const line = document.querySelector(".journal-entry-when > p");
      expect(line?.textContent).toMatch(
        labels === journalSv
          ? /^Onsdag 18 mars · \d\d:\d\d$/
          : /^Wednesday 18 March · \d\d:\d\d$/,
      );
      unmount();
    }
  });
});

describe("the neighbouring entries", () => {
  const entries = {
    [earlierId]: entryOf(earlierId, "Dagen innan", { journal_date: otherDay }),
    [firstId]: entryOf(firstId, "Morgon"),
    [secondId]: entryOf(secondId, "Lunch"),
    [thirdId]: entryOf(thirdId, "Kväll"),
  };

  function open(
    id: string,
    extra: Partial<JournalTransport> = {},
    pane?: "detail",
  ) {
    const view = (
      <JournalView
        transport={transportOf(entries, () => undefined, extra)}
        initial={{ kind: "entry", id }}
        labels={journalEn}
        fullscreen
      />
    );
    render(
      pane ? (
        <RoomSurfaceContext.Provider
          value={{ active: true, framed: true, pane }}
        >
          {view}
        </RoomSurfaceContext.Provider>
      ) : (
        view
      ),
    );
  }

  it("steps to the entry after and before in the day, with 44 px buttons named by the neighbour", async () => {
    const user = userEvent.setup();
    open(secondId);
    const next = await screen.findByRole("button", { name: /Next entry/ });
    expect(next).toHaveTextContent("Kväll");
    const previous = screen.getByRole("button", { name: /Previous entry/ });
    expect(previous).toHaveTextContent("Morgon");
    await user.click(next);
    expect(
      await screen.findByRole("heading", { level: 2, name: "Kväll" }),
    ).toBeInTheDocument();
  });

  it("steps to the nearest day with entries from the last entry of a day, when the transport can list the days", async () => {
    const user = userEvent.setup();
    open(firstId, {
      listEntryDates: vi.fn((from: string, to: string) =>
        Promise.resolve(
          [otherDay, day].filter((date) => date >= from && date <= to),
        ),
      ),
    });
    const previous = await screen.findByRole("button", {
      name: /Previous entry/,
    });
    // Another day is named by its day, as its entry is not read yet.
    expect(previous).toHaveTextContent("Tuesday 10 March");
    await user.click(previous);
    expect(
      await screen.findByRole("heading", { level: 2, name: "Dagen innan" }),
    ).toBeInTheDocument();
  });

  it("steps with k and j when no list stands beside the entry", async () => {
    const user = userEvent.setup();
    open(secondId);
    await screen.findByRole("button", { name: /Next entry/ });
    await user.keyboard("j");
    expect(
      await screen.findByRole("heading", { level: 2, name: "Kväll" }),
    ).toBeInTheDocument();
  });

  it("leaves j and k to the list when the entry is the detail of a split", async () => {
    const user = userEvent.setup();
    open(secondId, {}, "detail");
    await screen.findByRole("button", { name: /Next entry/ });
    await user.keyboard("j");
    await act(() => Promise.resolve());
    expect(
      screen.getByRole("heading", { level: 2, name: "Lunch" }),
    ).toBeInTheDocument();
  });

  it("changes the entry with e", async () => {
    const user = userEvent.setup();
    open(secondId);
    await screen.findByRole("heading", { level: 2, name: "Lunch" });
    await screen.findByRole("button", { name: /Next entry/ });
    await user.keyboard("e");
    expect(
      await screen.findByRole("group", { name: journalEn.edit }),
    ).toBeInTheDocument();
  });
});

describe("writing", () => {
  function form(
    props: Partial<Parameters<typeof EntryTextForm>[0]> = {},
    labels = journalSv,
  ) {
    const submit = vi.fn().mockResolvedValue(undefined);
    const onCancel = vi.fn();
    render(
      <EntryTextForm
        labels={labels}
        kind="new"
        signatureBase={day}
        submit={submit}
        onCancel={onCancel}
        {...props}
      />,
    );
    return { submit, onCancel };
  }

  it("counts the words in the quiet line under the field, in both languages", async () => {
    const user = userEvent.setup();
    form();
    expect(screen.getByText(/^Onsdag 18 mars · 0 ord$/)).toBeInTheDocument();
    await user.type(
      screen.getByLabelText(journalSv.entryTextLabel),
      "en två tre",
    );
    expect(screen.getByText(/^Onsdag 18 mars · 3 ord$/)).toBeInTheDocument();
  });

  it("says 1 word and 2 words in English", async () => {
    const user = userEvent.setup();
    form({}, journalEn);
    const text = screen.getByLabelText(journalEn.entryTextLabel);
    await user.type(text, "hello");
    expect(screen.getByText("Wednesday 18 March · 1 word")).toBeInTheDocument();
    await user.type(text, " there");
    expect(
      screen.getByText("Wednesday 18 March · 2 words"),
    ).toBeInTheDocument();
  });

  it("draws bare fields with the placeholders, and keeps the labels as their names", () => {
    form();
    const title = screen.getByLabelText(journalSv.titleLabel);
    const text = screen.getByLabelText(journalSv.entryTextLabel);
    expect(title).toHaveAttribute("placeholder", entryReadSv.titlePlaceholder);
    expect(text).toHaveAttribute("placeholder", entryReadSv.textPlaceholder);
    // The labels are read out but not drawn.
    expect(document.querySelector("label")).toHaveClass(
      "journal-visually-hidden",
    );
    // The line "Sparas på …" and the form's heading are gone from the page.
    expect(screen.queryByText(/Sparas på/)).toBeNull();
  });

  it("saves with Ctrl+Enter from the text and with Cmd+Enter from the title", async () => {
    const user = userEvent.setup();
    const { submit } = form();
    await user.type(screen.getByLabelText(journalSv.titleLabel), "Rubrik");
    await user.type(screen.getByLabelText(journalSv.entryTextLabel), "Text");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(1));
    expect(submit).toHaveBeenCalledWith(
      { title: "Rubrik", text: "Text" },
      expect.any(String),
    );
    screen.getByLabelText(journalSv.titleLabel).focus();
    await user.keyboard("{Meta>}{Enter}{/Meta}");
    await waitFor(() => expect(submit).toHaveBeenCalledTimes(2));
  });

  it("moves from the title to the text with Enter and does not save", async () => {
    const user = userEvent.setup();
    const { submit } = form();
    await user.type(
      screen.getByLabelText(journalSv.titleLabel),
      "Rubrik{Enter}",
    );
    expect(screen.getByLabelText(journalSv.entryTextLabel)).toHaveFocus();
    expect(submit).not.toHaveBeenCalled();
  });

  it("cancels with Escape at once when nothing is written", async () => {
    const user = userEvent.setup();
    const { onCancel } = form();
    await user.keyboard("{Escape}");
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("asks before it cancels when something is written, and a second Escape keeps writing", async () => {
    const user = userEvent.setup();
    const { onCancel } = form();
    await user.type(screen.getByLabelText(journalSv.entryTextLabel), "något");
    await user.keyboard("{Escape}");
    expect(screen.getByText(journalSv.discardAsk)).toBeInTheDocument();
    expect(onCancel).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(screen.queryByText(journalSv.discardAsk)).toBeNull();
    expect(onCancel).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    await user.click(
      await screen.findByRole("button", { name: journalSv.discardYes }),
    );
    expect(onCancel).toHaveBeenCalledTimes(1);
  });

  it("writes the text to add in the same fields, under the entry's own day", async () => {
    const user = userEvent.setup();
    form({ kind: "append", date: day, signatureBase: "e:1" });
    expect(screen.getByText("Onsdag 18 mars · 0 ord")).toBeInTheDocument();
    expect(screen.getByLabelText(journalSv.appendTextLabel)).toHaveAttribute(
      "placeholder",
      entryReadSv.appendPlaceholder,
    );
    await user.keyboard("{Escape}");
  });
});

describe("the editor", () => {
  it("shows the title once, as the field, and takes Ctrl+Enter and Escape", async () => {
    const user = userEvent.setup();
    const entries = {
      [firstId]: entryOf(firstId, "Morgon", {
        summary: "Min text.",
        summary_by: "you",
      }),
    };
    const updateEntry = vi.fn().mockResolvedValue({
      entry: { ...entries[firstId], title: "Ny", version: 2 },
    });
    render(
      <JournalView
        transport={transportOf(
          entries,
          () => sourceOf("manual_text", "Min text."),
          {
            updateEntry,
          },
        )}
        initial={{ kind: "entry", id: firstId }}
        labels={journalEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    );
    const title = screen.getByLabelText(journalEn.titleLabel);
    expect(title).toHaveValue("Morgon");
    // The heading is hidden while the field carries the title, so it is not on the page twice.
    expect(
      screen.getByRole("heading", { level: 2, name: "Morgon" }),
    ).toHaveClass("journal-visually-hidden");
    // The same fields and the same quiet line as writing a new entry.
    expect(title).toHaveClass("journal-focus-title");
    expect(screen.getByLabelText(journalEn.entryTextLabel)).toHaveClass(
      "journal-focus-text",
    );
    expect(
      screen.getByText("Wednesday 18 March · 2 words"),
    ).toBeInTheDocument();

    await user.clear(title);
    await user.type(title, "Ny");
    await user.keyboard("{Control>}{Enter}{/Control}");
    await waitFor(() => expect(updateEntry).toHaveBeenCalledTimes(1));
    expect(updateEntry.mock.calls[0]?.[2]).toMatchObject({ title: "Ny" });
  });

  it("asks before Escape leaves a changed entry, and leaves an unchanged one at once", async () => {
    const user = userEvent.setup();
    const entries = { [firstId]: entryOf(firstId, "Morgon") };
    render(
      <JournalView
        transport={transportOf(entries, () => undefined)}
        initial={{ kind: "entry", id: firstId }}
        labels={journalEn}
      />,
    );
    await user.click(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    );
    await user.keyboard("{Escape}");
    expect(screen.queryByRole("group", { name: journalEn.edit })).toBeNull();
    await user.click(
      await screen.findByRole("button", { name: journalEn.editEntry }),
    );
    await user.type(screen.getByLabelText(journalEn.titleLabel), "!");
    await user.keyboard("{Escape}");
    expect(screen.getByText(journalEn.discardAsk)).toBeInTheDocument();
    expect(screen.getByRole("group", { name: journalEn.edit })).toBeVisible();
  });
});

describe("the new labels", () => {
  it("have the same keys in Swedish and English and pick the language of the journal's labels", () => {
    expect(Object.keys(entryReadSv).sort()).toEqual(
      Object.keys(entryReadEn).sort(),
    );
    expect(entryReadFor(journalSv)).toBe(entryReadSv);
    expect(entryReadFor(journalEn)).toBe(entryReadEn);
    expect(entryReadEn.writeMeta(undefined, 1)).toBe("1 word");
    expect(entryReadSv.writeMeta(undefined, 1)).toBe("1 ord");
  });
});
