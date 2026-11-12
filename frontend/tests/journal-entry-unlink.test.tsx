import { act, render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";
import { EntryLinks } from "@/features/journal-app/entry-links";
import {
  journalEn,
  journalSv,
  type JournalLabels,
} from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalLinkChange,
  JournalTransport,
} from "@/features/journal-app/transport";

// EntryLinks in the entry's fullscreen view: chips with names, the remove question, the write at the
// entry's version, the Undo line, the failures and the focus around the question. The transport is faked.
const entryId = "019f0000-0000-7000-8000-0000000000e1";
const contactAnna = "019f0000-0000-7000-8000-0000000000c1";
const contactNoName = "019f0000-0000-7000-8000-0000000000c2";
const contactLars = "019f0000-0000-7000-8000-0000000000c3";
const projectOffer = "019f0000-0000-7000-8000-0000000000a1";
const projectOffice = "019f0000-0000-7000-8000-0000000000a2";

const created: JournalEntry = {
  id: entryId,
  source_id: "019f0000-0000-7000-8000-0000000000b1",
  journal_date: "2026-10-24",
  occurred_at: "2026-10-24T09:30:00Z",
  title: "Mötet om offerten",
  summary: "Kunden vill ha offerten före fredag.",
  key_points: [],
  project_ids: [projectOffer, projectOffice],
  task_ids: [],
  contact_ids: [contactAnna, contactNoName, contactLars],
  links: [
    { kind: "contact", id: contactAnna, label: "Anna Berg" },
    { kind: "project", id: projectOffer, label: "Offert Norr" },
    { kind: "contact", id: contactNoName, label: null },
    { kind: "contact", id: contactLars, label: "Lars Ek" },
    { kind: "project", id: projectOffice, label: "Kontor" },
  ],
  archived: false,
  version: 3,
};

/** The same entry after one link was removed: the version moves on and the link is gone. */
function without(
  entry: JournalEntry,
  id: string,
  version: number,
): JournalEntry {
  return {
    ...entry,
    links: entry.links?.filter((link) => link.id !== id),
    version,
  };
}

type Write = (
  entryId: string,
  version: number,
  change: JournalLinkChange,
  key: string,
) => Promise<{ entry: JournalEntry }>;

/** Holds the entry like the entry view does: the answer of a write becomes the next `entry`. */
function Harness({
  write,
  labels,
  initial = created,
  onOpenContact,
  withWrite = true,
}: {
  write: Write;
  labels: JournalLabels;
  initial?: JournalEntry;
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  withWrite?: boolean;
}) {
  const [entry, setEntry] = useState(initial);
  const transport = (
    withWrite ? { updateEntryLinks: write } : {}
  ) as JournalTransport;
  return (
    <EntryLinks
      entry={entry}
      labels={labels}
      transport={transport}
      onOpenContact={onOpenContact}
      onChanged={setEntry}
    />
  );
}

/** Answers a removal with the entry without the link, and an Undo with the link back at the next version. */
function standardWrite(): ReturnType<typeof vi.fn<Write>> {
  return vi.fn<Write>((_id, version, change) => {
    const removedId = (change.remove_contact_ids ??
      change.remove_project_ids)?.[0];
    if (removedId)
      return Promise.resolve({
        entry: without(created, removedId, version + 1),
      });
    return Promise.resolve({ entry: { ...created, version: version + 1 } });
  });
}

const sets = [
  ["en", journalEn],
  ["sv", journalSv],
] as const;

describe.each(sets)("EntryLinks (%s)", (_name, t) => {
  const removeButton = (name: string) =>
    screen.getByRole("button", { name: t.linkRemove(name) });
  const confirm = () =>
    screen.getByRole("button", { name: t.linkRemoveConfirm });

  /** Removing a link takes two steps: the cross asks, the confirmation removes. */
  async function removeLink(name: string) {
    await userEvent.click(removeButton(name));
    await userEvent.click(confirm());
  }

  it("shows every linked name as a chip, with fallbacks for a missing name", () => {
    render(<Harness write={standardWrite()} labels={t} />);

    expect(document.querySelectorAll(".journal-chip")).toHaveLength(5);
    expect(screen.getByText("Anna Berg")).toBeInTheDocument();
    expect(screen.getByText("Lars Ek")).toBeInTheDocument();
    expect(screen.getByText(t.linkContactFallback)).toBeInTheDocument();
    expect(screen.getByRole("list")).toHaveClass("journal-chips");
  });

  it("shows the project fallback when a project has no name", () => {
    render(
      <Harness
        write={standardWrite()}
        labels={t}
        initial={{
          ...created,
          links: [{ kind: "project", id: projectOffer, label: null }],
        }}
      />,
    );

    expect(screen.getByText(t.linkProjectFallback)).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: t.linkRemove(t.linkProjectFallback) }),
    ).toBeInTheDocument();
  });

  it("renders nothing when the entry has no links, or an older server sent none", () => {
    const { container, rerender } = render(
      <Harness
        write={standardWrite()}
        labels={t}
        initial={{ ...created, links: [] }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
    rerender(
      <Harness
        key="2"
        write={standardWrite()}
        labels={t}
        initial={{ ...created, links: undefined }}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the names without remove buttons when the transport cannot write links", () => {
    render(<Harness write={standardWrite()} labels={t} withWrite={false} />);

    expect(screen.getByText("Anna Berg")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: /Anna Berg/ }),
    ).not.toBeInTheDocument();
    expect(screen.queryByText("×")).not.toBeInTheDocument();
  });

  it("a contact name is a button that opens the contact; a project name is plain text", async () => {
    const onOpenContact = vi.fn();
    render(
      <Harness
        write={standardWrite()}
        labels={t}
        onOpenContact={onOpenContact}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Anna Berg" }));
    expect(onOpenContact).toHaveBeenCalledWith({
      id: contactAnna,
      label: "Anna Berg",
    });
    expect(screen.getByText("Offert Norr").tagName).toBe("SPAN");
    expect(screen.queryByRole("button", { name: "Offert Norr" })).toBeNull();
  });

  it("without onOpenContact a contact name is plain text", () => {
    render(<Harness write={standardWrite()} labels={t} />);

    expect(screen.getByText("Anna Berg").tagName).toBe("SPAN");
    expect(screen.queryByRole("button", { name: "Anna Berg" })).toBeNull();
  });

  it("the cross asks first; only the confirmation writes", async () => {
    const write = standardWrite();
    render(<Harness write={write} labels={t} />);

    await userEvent.click(removeButton("Anna Berg"));

    expect(write).not.toHaveBeenCalled();
    expect(screen.getByText(t.linkRemoveAsk("Anna Berg"))).toBeInTheDocument();
    // Two choices and nothing else to press.
    expect(screen.getAllByRole("button")).toHaveLength(2);
    await userEvent.click(confirm());
    expect(write).toHaveBeenCalledTimes(1);
  });

  it("Cancel leaves the link alone and brings the chips back", async () => {
    const write = standardWrite();
    render(<Harness write={write} labels={t} />);

    await userEvent.click(removeButton("Anna Berg"));
    await userEvent.click(screen.getByRole("button", { name: t.cancel }));

    expect(write).not.toHaveBeenCalled();
    expect(screen.queryByText(t.linkRemoveAsk("Anna Berg"))).toBeNull();
    expect(removeButton("Anna Berg")).toBeInTheDocument();
  });

  it("removes a contact link at the entry's version, offers Undo and reports the answer, without logging", async () => {
    const consoleMethods = ["log", "info", "warn", "error", "debug"] as const;
    const spies = consoleMethods.map((method) =>
      vi.spyOn(console, method).mockImplementation(() => undefined),
    );
    try {
      const write = standardWrite();
      const onChanged = vi.fn();
      const Wrapper = () => {
        const [entry, setEntry] = useState(created);
        return (
          <EntryLinks
            entry={entry}
            labels={t}
            transport={
              { updateEntryLinks: write } as unknown as JournalTransport
            }
            onChanged={(next) => {
              onChanged(next);
              setEntry(next);
            }}
          />
        );
      };
      render(<Wrapper />);
      await removeLink("Anna Berg");

      expect(
        await screen.findByText(t.linkRemoved("Anna Berg")),
      ).toBeInTheDocument();
      expect(write).toHaveBeenCalledWith(
        entryId,
        3,
        { remove_contact_ids: [contactAnna] },
        expect.any(String),
      );
      expect((write.mock.calls[0] as unknown[])[3]).toEqual(
        expect.stringMatching(/.{8,}/),
      );
      expect(onChanged).toHaveBeenCalledWith(
        expect.objectContaining({ version: 4 }),
      );
      expect(
        screen.queryByRole("button", { name: t.linkRemove("Anna Berg") }),
      ).not.toBeInTheDocument();
      expect(screen.getByText("Lars Ek")).toBeInTheDocument();
      expect(screen.getByRole("button", { name: t.undo })).toBeInTheDocument();
      for (const spy of spies) expect(spy).not.toHaveBeenCalled();
    } finally {
      spies.forEach((spy) => spy.mockRestore());
    }
  });

  it("removes a project link with remove_project_ids", async () => {
    const write = standardWrite();
    render(<Harness write={write} labels={t} />);
    await removeLink("Offert Norr");

    expect(write).toHaveBeenCalledWith(
      entryId,
      3,
      { remove_project_ids: [projectOffer] },
      expect.any(String),
    );
    expect(
      await screen.findByText(t.linkRemoved("Offert Norr")),
    ).toBeInTheDocument();
  });

  it("Undo adds the link back with the new version and a new key, then removes the Undo line", async () => {
    const write = standardWrite();
    render(<Harness write={write} labels={t} />);
    await removeLink("Anna Berg");
    await screen.findByText(t.linkRemoved("Anna Berg"));
    const removeKey = (write.mock.calls[0] as unknown[])[3];

    await userEvent.click(screen.getByRole("button", { name: t.undo }));

    await waitFor(() =>
      expect(
        screen.queryByText(t.linkRemoved("Anna Berg")),
      ).not.toBeInTheDocument(),
    );
    expect(write).toHaveBeenLastCalledWith(
      entryId,
      4,
      { add_contact_ids: [contactAnna] },
      expect.any(String),
    );
    expect((write.mock.lastCall as unknown[])[3]).not.toBe(removeKey);
    expect(removeButton("Anna Berg")).toBeInTheDocument();
  });

  it("shows an alert when the removal fails and keeps the chips", async () => {
    const write = vi.fn<Write>(() =>
      Promise.reject(new Error("Host request failed")),
    );
    render(<Harness write={write} labels={t} />);
    await removeLink("Anna Berg");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      t.linkRemoveFailed,
    );
    expect(removeButton("Anna Berg")).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: t.undo }),
    ).not.toBeInTheDocument();
  });

  it("an answer without an entry is a failed removal too", async () => {
    const write = vi.fn<Write>(() =>
      Promise.reject(new Error("update_journal_entry returned no entry")),
    );
    render(<Harness write={write} labels={t} />);
    await removeLink("Lars Ek");

    expect(await screen.findByRole("alert")).toHaveTextContent(
      t.linkRemoveFailed,
    );
  });

  it("a retry of the same failed removal reuses the idempotency key", async () => {
    const write = vi
      .fn<Write>()
      .mockRejectedValueOnce(new Error("Host request failed"))
      .mockImplementation((_id, version) =>
        Promise.resolve({ entry: without(created, contactAnna, version + 1) }),
      );
    render(<Harness write={write} labels={t} />);
    await removeLink("Anna Berg");
    await screen.findByRole("alert");

    await removeLink("Anna Berg");
    await screen.findByText(t.linkRemoved("Anna Berg"));

    expect(write).toHaveBeenCalledTimes(2);
    expect((write.mock.calls[1] as unknown[])[3]).toBe(
      (write.mock.calls[0] as unknown[])[3],
    );
  });

  it("shows the conflict text when the entry changed elsewhere", async () => {
    const write = vi.fn<Write>(() =>
      Promise.reject(
        Object.assign(new Error("conflict"), { code: "conflict" }),
      ),
    );
    render(<Harness write={write} labels={t} />);
    await removeLink("Anna Berg");

    expect(await screen.findByRole("alert")).toHaveTextContent(t.linkConflict);
  });

  it("keeps the Undo line and shows an alert when Undo fails", async () => {
    const write = vi.fn<Write>((_id, version, change) =>
      change.add_contact_ids
        ? Promise.reject(new Error("Host request failed"))
        : Promise.resolve({
            entry: without(created, contactAnna, version + 1),
          }),
    );
    render(<Harness write={write} labels={t} />);
    await removeLink("Anna Berg");
    await screen.findByText(t.linkRemoved("Anna Berg"));

    await userEvent.click(screen.getByRole("button", { name: t.undo }));

    expect(await screen.findByRole("alert")).toHaveTextContent(
      t.linkRestoreFailed,
    );
    expect(screen.getByText(t.linkRemoved("Anna Berg"))).toBeInTheDocument();
    expect(screen.getByRole("button", { name: t.undo })).toBeEnabled();
  });

  it("disables the link buttons while a link write waits for the host", async () => {
    let answer: (value: { entry: JournalEntry }) => void = () => undefined;
    const write = vi.fn<Write>(
      () =>
        new Promise((resolve) => {
          answer = resolve;
        }),
    );
    render(<Harness write={write} labels={t} />);
    await removeLink("Offert Norr");

    expect(removeButton("Anna Berg")).toBeDisabled();
    expect(removeButton("Kontor")).toBeDisabled();

    act(() => {
      answer({ entry: without(created, projectOffer, 4) });
    });
    expect(
      await screen.findByText(t.linkRemoved("Offert Norr")),
    ).toBeInTheDocument();
    expect(removeButton("Anna Berg")).toBeEnabled();
  });

  describe("focus around the removal question", () => {
    it("does not take focus when it first renders", () => {
      render(<Harness write={standardWrite()} labels={t} />);

      expect(document.body).toHaveFocus();
    });

    it("moves focus to the confirmation when the question opens", async () => {
      render(<Harness write={standardWrite()} labels={t} />);

      await userEvent.click(removeButton("Anna Berg"));

      expect(confirm()).toHaveFocus();
    });

    it("Cancel gives focus back to the chip's remove button", async () => {
      const write = standardWrite();
      render(<Harness write={write} labels={t} />);

      await userEvent.click(removeButton("Anna Berg"));
      await userEvent.click(screen.getByRole("button", { name: t.cancel }));

      expect(write).not.toHaveBeenCalled();
      expect(removeButton("Anna Berg")).toHaveFocus();
    });

    it("Escape closes the question without a removal and gives focus back to the chip", async () => {
      const write = standardWrite();
      render(<Harness write={write} labels={t} />);

      await userEvent.click(removeButton("Anna Berg"));
      await userEvent.keyboard("{Escape}");

      expect(write).not.toHaveBeenCalled();
      expect(screen.queryByText(t.linkRemoveAsk("Anna Berg"))).toBeNull();
      expect(removeButton("Anna Berg")).toHaveFocus();
    });

    it("after the confirmation focus goes to the link group, since the chip is gone", async () => {
      render(<Harness write={standardWrite()} labels={t} />);

      await userEvent.click(removeButton("Anna Berg"));
      await userEvent.click(confirm());
      await screen.findByText(t.linkRemoved("Anna Berg"));

      expect(screen.getByRole("group", { name: t.linked })).toHaveFocus();
    });
  });
});
