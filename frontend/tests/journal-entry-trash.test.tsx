import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { HostToolError } from "@/features/mcp-apps/bridge";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { JournalView } from "@/features/journal-app/journal-view";
import {
  journalEn,
  journalSv,
  type JournalLabels,
} from "@/features/journal-app/labels";
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
    updateEntry: vi.fn(),
    appendEntryText: vi.fn(),
    trashEntry: vi.fn().mockResolvedValue({ version: 8 }),
    restoreEntry: vi.fn().mockResolvedValue({}),
    ...extra,
  } as unknown as JournalTransport;
}

async function openMenuAndDelete(
  user: ReturnType<typeof userEvent.setup>,
  labels: JournalLabels,
) {
  await screen.findByRole("heading", { name: entry.title });
  await user.click(
    screen.getByRole("button", { name: labels.entryMoreActions }),
  );
  await user.click(screen.getByRole("button", { name: labels.deleteEntry }));
}

describe("the entry's action row", () => {
  it.each([
    ["sv", journalSv],
    ["en", journalEn],
  ] as const)(
    "draws edit and add text as two equal secondary buttons (%s)",
    async (_name, labels) => {
      render(
        <JournalView
          transport={transport()}
          initial={entryRoot}
          labels={labels}
        />,
      );
      const edit = await screen.findByRole("button", {
        name: labels.editEntry,
      });
      const add = screen.getByRole("button", { name: labels.appendText });
      for (const button of [edit, add]) {
        expect(button).toHaveClass("sk-btn--secondary");
        expect(button).not.toHaveClass("sk-btn--compact");
        expect(button).not.toHaveClass("sk-btn--quiet");
      }
      expect(edit.parentElement).toBe(add.parentElement);
      expect(edit.parentElement).toHaveClass("journal-actions");
    },
  );
});

describe("deleting an entry", () => {
  it("offers no delete when the host has no trash tools", async () => {
    render(
      <JournalView
        transport={transport({
          trashEntry: undefined,
          restoreEntry: undefined,
        })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await screen.findByRole("heading", { name: entry.title });
    expect(
      screen.queryByRole("button", { name: journalSv.entryMoreActions }),
    ).toBeNull();
  });

  it("moves the entry to the trash at once, without asking, and Undo restores it", async () => {
    const user = userEvent.setup();
    const trashEntry = vi.fn().mockResolvedValue({ version: 8 });
    const restoreEntry = vi.fn().mockResolvedValue({});
    const getEntry = vi.fn().mockResolvedValue({ entry });
    render(
      <JournalView
        transport={transport({ trashEntry, restoreEntry, getEntry })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenuAndDelete(user, journalSv);
    expect(await screen.findByText(journalSv.entryTrashed)).toBeVisible();
    expect(trashEntry).toHaveBeenCalledWith(
      entryId,
      3,
      expect.stringMatching(/.{8,}/),
    );
    // The original actions are gone while the entry is in the trash; Undo is the one thing to do.
    expect(
      screen.queryByRole("button", { name: journalSv.editEntry }),
    ).toBeNull();
    expect(screen.getByText(/Minne och kontroll › Borttaget/)).toBeVisible();

    await user.click(screen.getByRole("button", { name: journalSv.undo }));
    await waitFor(() =>
      expect(restoreEntry).toHaveBeenCalledWith(
        entryId,
        8,
        expect.stringMatching(/.{8,}/),
      ),
    );
    expect(await screen.findByText(journalSv.entryRestored)).toBeVisible();
    expect(
      screen.getByRole("button", { name: journalSv.editEntry }),
    ).toBeVisible();
    expect(getEntry).toHaveBeenCalledTimes(2);
  });

  it("says so on a failure and retries with the same idempotency key", async () => {
    const user = userEvent.setup();
    const trashEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValue({ version: 8 });
    render(
      <JournalView
        transport={transport({ trashEntry })}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await openMenuAndDelete(user, journalEn);
    expect(await screen.findByText(journalEn.entryTrashFailed)).toBeVisible();
    // The entry is still there, so nothing is lost.
    expect(
      screen.getByRole("button", { name: journalEn.editEntry }),
    ).toBeVisible();
    await user.click(screen.getByRole("button", { name: journalEn.retry }));
    expect(await screen.findByText(journalEn.entryTrashed)).toBeVisible();
    expect(trashEntry).toHaveBeenCalledTimes(2);
    expect(trashEntry.mock.calls[1]![2]).toBe(trashEntry.mock.calls[0]![2]);
  });

  it("reads the entry again on a stale version", async () => {
    const user = userEvent.setup();
    const trashEntry = vi.fn().mockRejectedValue(new HostToolError("conflict"));
    const getEntry = vi.fn().mockResolvedValue({ entry });
    render(
      <JournalView
        transport={transport({ trashEntry, getEntry })}
        initial={entryRoot}
        labels={journalSv}
      />,
    );
    await openMenuAndDelete(user, journalSv);
    expect(
      await screen.findByText(journalSv.entryReloadedConflict),
    ).toBeVisible();
    await waitFor(() => expect(getEntry).toHaveBeenCalledTimes(2));
  });

  it("keeps Undo on screen with a calm line when Undo fails, and tries again", async () => {
    const user = userEvent.setup();
    const restoreEntry = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("internal_error"))
      .mockResolvedValue({});
    render(
      <JournalView
        transport={transport({ restoreEntry })}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await openMenuAndDelete(user, journalEn);
    await user.click(
      await screen.findByRole("button", { name: journalEn.undo }),
    );
    expect(await screen.findByText(journalEn.entryRestoreFailed)).toBeVisible();
    await user.click(screen.getByRole("button", { name: journalEn.undo }));
    expect(await screen.findByText(journalEn.entryRestored)).toBeVisible();
    expect(restoreEntry.mock.calls[1]![2]).toBe(restoreEntry.mock.calls[0]![2]);
  });

  it("closes the menu with Escape and returns focus to the ⋯", async () => {
    const user = userEvent.setup();
    render(
      <JournalView
        transport={transport()}
        initial={entryRoot}
        labels={journalEn}
      />,
    );
    await screen.findByRole("heading", { name: entry.title });
    const more = screen.getByRole("button", {
      name: journalEn.entryMoreActions,
    });
    await user.click(more);
    const item = screen.getByRole("button", { name: journalEn.deleteEntry });
    item.focus();
    await user.keyboard("{Escape}");
    expect(
      screen.queryByRole("button", { name: journalEn.deleteEntry }),
    ).toBeNull();
    expect(more).toHaveFocus();
  });

  it("puts the ⋯ in the shell's Back row when the shell draws one", async () => {
    const slot = document.createElement("span");
    document.body.append(slot);
    render(
      <RoomSurfaceContext.Provider
        value={{ active: true, framed: true, backActions: slot }}
      >
        <JournalView
          transport={transport()}
          initial={entryRoot}
          labels={journalSv}
        />
      </RoomSurfaceContext.Provider>,
    );
    await screen.findByRole("heading", { name: entry.title });
    expect(
      slot.querySelector(`[aria-label="${journalSv.entryMoreActions}"]`),
    ).not.toBeNull();
    slot.remove();
  });
});

describe("the trash tools through the transport", () => {
  it("maps delete and Undo to move_to_trash and restore_from_trash", async () => {
    const call = vi.fn().mockResolvedValue({ version: 8 });
    const t = createJournalTransport(call, true, true, true);
    await t.trashEntry!(entryId, 3, "key-00000001");
    await t.restoreEntry!(entryId, 8, "key-00000002");
    expect(call.mock.calls).toEqual([
      [
        "move_to_trash",
        {
          kind: "journal_entry",
          record_id: entryId,
          version: 3,
          idempotency_key: "key-00000001",
        },
      ],
      [
        "restore_from_trash",
        {
          kind: "journal_entry",
          record_id: entryId,
          version: 8,
          idempotency_key: "key-00000002",
        },
      ],
    ]);
  });

  it("has no trash tools unless the host offers them", () => {
    const t = createJournalTransport(vi.fn());
    expect(t.trashEntry).toBeUndefined();
    expect(t.restoreEntry).toBeUndefined();
  });
});

describe("labels", () => {
  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(journalSv).sort()).toEqual(
      Object.keys(journalEn).sort(),
    );
  });
});
