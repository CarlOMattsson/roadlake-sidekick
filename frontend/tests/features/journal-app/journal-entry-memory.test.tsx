import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { JournalView } from "@/features/journal-app/journal-view";
import { EntryRow } from "@/features/journal-app/entry-row";
import {
  journalEn,
  journalSv,
  type JournalLabels,
} from "@/features/journal-app/labels";
import { receiptText } from "@/features/journal-app/receipt-text";
import {
  createJournalTransport,
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
  summary_by: null,
  memory_excluded: false,
  key_points: [],
  project_ids: [],
  task_ids: [],
  contact_ids: [],
  tags: [],
  archived: false,
  version: 3,
};
const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function transport(extra: Partial<JournalTransport> = {}, found = entry) {
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
    trashEntry: vi.fn().mockResolvedValue({ version: 8 }),
    restoreEntry: vi.fn().mockResolvedValue({}),
    excludeEntryFromMemory: vi.fn().mockResolvedValue({ changed: true }),
    ...extra,
  } satisfies JournalTransport;
}

async function openMenu(
  user: ReturnType<typeof userEvent.setup>,
  labels: JournalLabels,
) {
  await screen.findByRole("heading", { name: entry.title });
  await user.click(
    screen.getByRole("button", { name: labels.entryMoreActions }),
  );
}

describe("keeping an entry out of Claude's memory", () => {
  it.each([
    ["sv", journalSv],
    ["en", journalEn],
  ] as const)(
    "keeps it out, shows the marker and the status line, and brings it back (%s)",
    async (_name, labels) => {
      const user = userEvent.setup();
      const excludeEntryFromMemory = vi.fn().mockResolvedValue({});
      const getEntry = vi.fn().mockResolvedValue({ entry });
      render(
        <JournalView
          transport={transport({ excludeEntryFromMemory, getEntry })}
          initial={entryRoot}
          labels={labels}
        />,
      );
      expect(screen.queryByText(labels.entryOutOfMemory)).toBeNull();
      await openMenu(user, labels);
      await user.click(
        screen.getByRole("button", { name: labels.entryKeepOutOfMemory }),
      );
      expect(
        await screen.findByText(receiptText(labels.entryKeptOutOfMemory)),
      ).toBeVisible();
      expect(excludeEntryFromMemory).toHaveBeenCalledWith(entryId, true);
      expect(screen.getByText(labels.entryOutOfMemory)).toBeVisible();
      // The version did not change: no second read, and the other actions stay.
      expect(getEntry).toHaveBeenCalledTimes(1);
      expect(
        screen.getByRole("button", { name: labels.editEntry }),
      ).toBeVisible();

      await user.click(
        screen.getByRole("button", { name: labels.entryMoreActions }),
      );
      await user.click(
        screen.getByRole("button", { name: labels.entryBringBackIntoMemory }),
      );
      expect(
        await screen.findByText(receiptText(labels.entryBackInMemory)),
      ).toBeVisible();
      expect(excludeEntryFromMemory).toHaveBeenLastCalledWith(entryId, false);
      expect(screen.queryByText(labels.entryOutOfMemory)).toBeNull();
    },
  );

  it("offers to bring back an entry that arrives excluded", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport({}, { ...entry, memory_excluded: true })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenu(user, journalSv);
    expect(screen.getByText(journalSv.entryOutOfMemory)).toBeVisible();
    expect(
      screen.getByRole("button", { name: "Ta med i minnet igen" }),
    ).toBeVisible();
    expect(
      screen.queryByRole("button", { name: "Håll utanför minnet" }),
    ).toBeNull();
  });

  it("has no such item when the transport lacks the capability", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport({ excludeEntryFromMemory: undefined })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenu(user, journalSv);
    expect(
      screen.getByRole("button", { name: journalSv.deleteEntry }),
    ).toBeVisible();
    expect(screen.queryByRole("button", { name: /minnet/ })).toBeNull();
  });

  it("says plainly when the write fails and tries the same choice again", async () => {
    const user = userEvent.setup();
    const excludeEntryFromMemory = vi
      .fn()
      .mockRejectedValueOnce(new Error("down"))
      .mockResolvedValue({});
    render(
      <JournalView
        transport={transport({ excludeEntryFromMemory })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenu(user, journalSv);
    await user.click(
      screen.getByRole("button", { name: journalSv.entryKeepOutOfMemory }),
    );
    expect(await screen.findByText(journalSv.entryMemoryFailed)).toBeVisible();
    expect(screen.queryByText(journalSv.entryOutOfMemory)).toBeNull();

    await user.click(screen.getByRole("button", { name: /Försök igen/ }));
    expect(
      await screen.findByText(receiptText(journalSv.entryKeptOutOfMemory)),
    ).toBeVisible();
    expect(excludeEntryFromMemory).toHaveBeenCalledTimes(2);
    expect(excludeEntryFromMemory).toHaveBeenLastCalledWith(entryId, true);
    expect(screen.queryByText(journalSv.entryMemoryFailed)).toBeNull();
  });

  it("explains a refusal without a retry", async () => {
    const user = userEvent.setup();
    const excludeEntryFromMemory = vi
      .fn()
      .mockRejectedValue(new HostToolError("forbidden"));
    render(
      <JournalView
        transport={transport({ excludeEntryFromMemory })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenu(user, journalSv);
    await user.click(
      screen.getByRole("button", { name: journalSv.entryKeepOutOfMemory }),
    );
    await waitFor(() =>
      expect(screen.getByText(journalSv.forbiddenWrite)).toBeVisible(),
    );
  });
});

describe("the memory marker on a day row", () => {
  it("marks an excluded entry with a chip in the row's meta line, with no extra line", () => {
    const { container } = render(
      <ul>
        <EntryRow
          entry={{ ...entry, memory_excluded: true }}
          labels={journalSv}
        />
      </ul>,
    );
    const chip = container.querySelector(
      ".journal-entry-meta > .journal-memory-chip",
    );
    expect(chip?.textContent).toBe(journalSv.entryOutOfMemory);
    // A marker, not a control: no button of its own, and its icon is not announced.
    expect(chip?.closest("button")).toBeNull();
    expect(chip?.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    // The meta text carries no marker any more.
    expect(container.querySelector(".sk-row-meta")).toBeNull();
  });

  it("shows no marker for an entry in memory", () => {
    render(
      <ul>
        <EntryRow entry={entry} labels={journalSv} />
      </ul>,
    );
    expect(screen.queryByText(journalSv.entryOutOfMemory)).toBeNull();
  });
});

describe("the memory tool through the transport", () => {
  it("maps the choice to exclude_from_memory for a journal entry", async () => {
    const call = vi.fn().mockResolvedValue({});
    const t = createJournalTransport(
      call,
      true,
      true,
      false,
      false,
      undefined,
      true,
    );
    await t.excludeEntryFromMemory!(entryId, true);
    expect(call).toHaveBeenCalledWith("exclude_from_memory", {
      kind: "journal_entry",
      id: entryId,
      excluded: true,
    });
  });

  it("has no such tool unless the host offers it", () => {
    expect(
      createJournalTransport(vi.fn()).excludeEntryFromMemory,
    ).toBeUndefined();
  });
});
