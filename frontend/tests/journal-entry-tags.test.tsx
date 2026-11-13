import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EntryCard } from "@/features/journal-app/entry-card";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import {
  createJournalTransport,
  type JournalFrame,
} from "@/features/journal-app/transport";
import { HostToolError } from "@/features/mcp-apps/bridge";
import {
  day,
  entry,
  entryId,
  transportMock,
  type TransportMock,
} from "./helpers/journal-app-fixtures";
import { listTagsMock, taggedEntry } from "./helpers/journal-tag-fixtures";

const entryRoot: JournalFrame = { kind: "entry", id: entryId };

function renderEntry(transport: TransportMock, labels = journalEn) {
  return render(
    <JournalView transport={transport} initial={entryRoot} labels={labels} />,
  );
}

/** The tag write: answers with the entry carrying the new set at the next version. */
function tagWrite() {
  return vi.fn((_id: string, _version: number, next: string[]) =>
    Promise.resolve({ entry: { ...entry, tags: next, version: 2 } }),
  );
}

async function openEditor(user: ReturnType<typeof userEvent.setup>) {
  await screen.findByRole("heading", { level: 2, name: entry.title });
  await user.click(
    await screen.findByRole("button", { name: /^(Add tag|Edit tags)/ }),
  );
}

describe("the tool calls of the tag parts", () => {
  it("maps the vocabulary, the tagged read and the tag write to their tools", async () => {
    const call = vi.fn().mockResolvedValue({ tags: [], entry, entries: [] });
    const t = createJournalTransport(call, true, true, false, false, {
      vocabulary: true,
      filter: true,
      write: true,
    });
    await t.listTags!();
    await t.listTaggedEntries!(["a", "b"], "2025-11-13", "2026-11-13", "c1");
    await t.updateEntryTags!(entryId, 3, ["a"], "key-00000001");
    expect(call.mock.calls).toEqual([
      ["list_tags", { limit: 100 }],
      [
        "list_journal_entries",
        {
          from_date: "2025-11-13",
          to_date: "2026-11-13",
          tags: ["a", "b"],
          tag_match: "all",
          include_content: false,
          limit: 50,
          cursor: "c1",
        },
      ],
      [
        "update_journal_entry",
        {
          entry_id: entryId,
          expected_version: 3,
          idempotency_key: "key-00000001",
          tags: ["a"],
        },
      ],
    ]);
  });

  it("leaves out what the host does not answer", () => {
    const t = createJournalTransport(vi.fn());
    expect(t.listTags).toBeUndefined();
    expect(t.listTaggedEntries).toBeUndefined();
    expect(t.updateEntryTags).toBeUndefined();
  });
});

describe("tags in the entry view", () => {
  it("shows the tags by their label, and a tag the vocabulary does not know by its slug", async () => {
    const getEntry = vi.fn(() =>
      Promise.resolve({ entry: taggedEntry(["viktig", "okand"]) }),
    );
    renderEntry(
      transportMock({
        getEntry,
        listTags: listTagsMock(),
        updateEntryTags: tagWrite(),
      }),
    );
    expect(
      await screen.findByText("Tags: Viktig and okand"),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Edit tags for Mötet om offerten" }),
    ).toBeInTheDocument();
  });

  it("writes the complete set at the entry's version, shows it and reads the vocabulary again", async () => {
    const user = userEvent.setup();
    const listTags = listTagsMock();
    const updateEntryTags = tagWrite();
    renderEntry(transportMock({ listTags, updateEntryTags }));
    await openEditor(user);

    await user.type(screen.getByLabelText("New tag"), "Viktig{Enter}");

    await waitFor(() => expect(updateEntryTags).toHaveBeenCalledTimes(1));
    expect(updateEntryTags).toHaveBeenCalledWith(
      entryId,
      1,
      ["viktig"],
      expect.stringMatching(/^[0-9a-f-]{36}$/),
    );
    expect(
      await screen.findByRole("button", { name: "Remove tag Viktig" }),
    ).toBeInTheDocument();
    await waitFor(() => expect(listTags).toHaveBeenCalledTimes(2));
  });

  it("removes a tag by sending the rest of the set", async () => {
    const user = userEvent.setup();
    const getEntry = vi.fn(() =>
      Promise.resolve({ entry: taggedEntry(["viktig", "familj"]) }),
    );
    const updateEntryTags = tagWrite();
    renderEntry(
      transportMock({ getEntry, listTags: listTagsMock(), updateEntryTags }),
    );
    await openEditor(user);

    await user.click(screen.getByRole("button", { name: "Remove tag Viktig" }));

    await waitFor(() => expect(updateEntryTags).toHaveBeenCalledTimes(1));
    expect(updateEntryTags.mock.calls[0]?.slice(0, 3)).toEqual([
      entryId,
      1,
      ["familj"],
    ]);
    await waitFor(() =>
      expect(
        screen.queryByRole("button", { name: "Remove tag Viktig" }),
      ).toBeNull(),
    );
  });

  it("keeps what was typed after a failed write and retries it with the same key", async () => {
    const user = userEvent.setup();
    const updateEntryTags = vi
      .fn()
      .mockRejectedValueOnce(new Error("offline"))
      .mockImplementationOnce(() =>
        Promise.resolve({ entry: { ...entry, tags: ["viktig"], version: 2 } }),
      );
    renderEntry(transportMock({ listTags: listTagsMock(), updateEntryTags }));
    await openEditor(user);

    await user.type(screen.getByLabelText("New tag"), "viktig{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      journalEn.tagsFailed,
    );
    expect(screen.getByLabelText("New tag")).toHaveValue("viktig");

    await user.click(screen.getByRole("button", { name: "Add" }));

    await waitFor(() => expect(updateEntryTags).toHaveBeenCalledTimes(2));
    expect(updateEntryTags.mock.calls[1]?.[3]).toBe(
      updateEntryTags.mock.calls[0]?.[3],
    );
    await waitFor(() => expect(screen.queryByRole("alert")).toBeNull());
  });

  it("reads the entry again on a conflict and says so", async () => {
    const user = userEvent.setup();
    const getEntry = vi.fn(() => Promise.resolve({ entry }));
    const updateEntryTags = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    renderEntry(
      transportMock({ getEntry, listTags: listTagsMock(), updateEntryTags }),
    );
    await openEditor(user);

    await user.type(screen.getByLabelText("New tag"), "viktig{Enter}");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      journalEn.tagsConflict,
    );
    await waitFor(() => expect(getEntry).toHaveBeenCalledTimes(2));
  });

  it("names a refused write, and a write without permission", async () => {
    const user = userEvent.setup();
    const updateEntryTags = vi
      .fn()
      .mockRejectedValueOnce(new HostToolError("validation_error"))
      .mockRejectedValueOnce(new HostToolError("forbidden"));
    renderEntry(transportMock({ listTags: listTagsMock(), updateEntryTags }));
    await openEditor(user);

    await user.type(screen.getByLabelText("New tag"), "viktig{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      journalEn.tagsInvalid,
    );
    await user.click(screen.getByRole("button", { name: "Add" }));
    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(
        journalEn.forbiddenWrite,
      ),
    );
  });

  it("shows an archived entry's tags and offers no editing", async () => {
    const getEntry = vi.fn(() =>
      Promise.resolve({ entry: taggedEntry(["viktig"], { archived: true }) }),
    );
    renderEntry(
      transportMock({
        getEntry,
        listTags: listTagsMock(),
        updateEntryTags: tagWrite(),
      }),
    );
    expect(await screen.findByText("Tags: Viktig")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tags/i })).toBeNull();
  });

  it("offers no editing where the host has no tag write, but still shows the tags", async () => {
    const getEntry = vi.fn(() =>
      Promise.resolve({ entry: taggedEntry(["viktig"]) }),
    );
    renderEntry(transportMock({ getEntry }));
    expect(await screen.findByText("Tags: viktig")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: /tags/i })).toBeNull();
  });

  it("shows nothing about tags for an entry without any where the host has no tag write", async () => {
    renderEntry(transportMock());
    await screen.findByRole("heading", { level: 2, name: entry.title });
    expect(screen.queryByText(/^Tags:/)).toBeNull();
    expect(screen.queryByRole("button", { name: /tag/i })).toBeNull();
  });

  it("speaks Swedish, with the same parts", async () => {
    const user = userEvent.setup();
    const updateEntryTags = vi
      .fn()
      .mockRejectedValue(new HostToolError("conflict"));
    renderEntry(
      transportMock({ listTags: listTagsMock(), updateEntryTags }),
      journalSv,
    );
    await screen.findByRole("heading", { level: 2, name: entry.title });
    await user.click(
      await screen.findByRole("button", { name: "Lägg till tagg" }),
    );
    await user.type(screen.getByLabelText("Ny tagg"), "viktig{Enter}");
    expect(await screen.findByRole("alert")).toHaveTextContent(
      journalSv.tagsConflict,
    );
  });
});

describe("tags on a day's rows and on the card", () => {
  it("closes a row's meta line with its tags, by label", async () => {
    const day24 = day("2026-10-24", [taggedEntry(["viktig", "familj"])]);
    render(
      <JournalView
        transport={transportMock({ listTags: listTagsMock() })}
        initial={{ kind: "day", page: day24 }}
        labels={journalEn}
      />,
    );
    expect(
      await screen.findByText("Tags: Viktig and Familj"),
    ).toBeInTheDocument();
  });

  it("shows two tags on the card's meta line and counts the rest", () => {
    const card = taggedEntry(["a", "b", "c"]);
    render(
      <EntryCard
        entry={{
          id: card.id,
          title: card.title,
          summary: null,
          tags: card.tags,
        }}
        today="2026-10-24"
        labels={journalEn}
        onOpen={vi.fn()}
      />,
    );
    expect(
      document.querySelectorAll(
        ".journal-card-links .sk-tag:not(.sk-tag--more)",
      ),
    ).toHaveLength(2);
    expect(
      document.querySelector(".journal-card-links .sk-tag--more"),
    ).toHaveTextContent("+1");
  });

  it("adds nothing to a card without tags", () => {
    render(
      <EntryCard
        entry={{ id: entryId, title: "Titel", summary: null, tags: [] }}
        today="2026-10-24"
        labels={journalSv}
        onOpen={vi.fn()}
      />,
    );
    expect(document.querySelector(".sk-tags")).toBeNull();
  });
});
