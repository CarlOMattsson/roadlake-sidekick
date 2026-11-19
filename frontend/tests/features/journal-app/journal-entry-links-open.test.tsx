import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { EntryLinks } from "@/features/journal-app/entry-links";
import { journalEn } from "@/features/journal-app/labels";
import type {
  JournalEntry,
  JournalTransport,
} from "@/features/journal-app/transport";

const entry = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  version: 2,
  links: [
    { kind: "project", id: "p1", label: "Offert Norr" },
    { kind: "contact", id: "c1", label: "Anna Berg" },
  ],
} as unknown as JournalEntry;

/** A transport that cannot write links: the chips have no remove button, only (maybe) an open button. */
const readOnly = {} as JournalTransport;

function renderLinks(props: Partial<Parameters<typeof EntryLinks>[0]> = {}) {
  return render(
    <EntryLinks
      entry={entry}
      labels={journalEn}
      transport={readOnly}
      onChanged={vi.fn()}
      onConflict={vi.fn()}
      removable={false}
      {...props}
    />,
  );
}

describe("the Linked chips of an entry", () => {
  it("open their Contact or Project when the host gives the way to", async () => {
    const user = userEvent.setup();
    const onOpenContact = vi.fn();
    const onOpenProject = vi.fn();
    renderLinks({ onOpenContact, onOpenProject });

    await user.click(screen.getByRole("button", { name: "Offert Norr" }));
    expect(onOpenProject).toHaveBeenCalledWith({
      id: "p1",
      label: "Offert Norr",
    });
    await user.click(screen.getByRole("button", { name: "Anna Berg" }));
    expect(onOpenContact).toHaveBeenCalledWith({
      id: "c1",
      label: "Anna Berg",
    });
  });

  it("are plain names, with no frame, when they cannot be opened or removed", () => {
    renderLinks();

    expect(screen.queryByRole("button")).toBeNull();
    for (const name of ["Offert Norr", "Anna Berg"]) {
      expect(screen.getByText(name).closest("li")).toHaveClass(
        "journal-chip--static",
      );
    }
  });

  it("keep their frame only where the chip opens", () => {
    renderLinks({ onOpenProject: vi.fn() });

    const project = screen.getByRole("button", { name: "Offert Norr" });
    expect(project.closest("li")).not.toHaveClass("journal-chip--static");
    expect(screen.getByText("Anna Berg").closest("li")).toHaveClass(
      "journal-chip--static",
    );
  });
});
