import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import {
  EntryCard,
  type EntryCardData,
} from "@/features/journal-app/entry-card";
import { journalEn } from "@/features/journal-app/labels";
import type { JournalEntryLink } from "@/features/journal-app/transport";

const contact: JournalEntryLink = {
  kind: "contact",
  id: "c1",
  label: "Anna Andersson",
};
const project: JournalEntryLink = { kind: "project", id: "p1", label: "Köket" };

const entry: EntryCardData = {
  id: "019f0000-0000-7000-8000-0000000000e1",
  title: "Mötet om offerten",
  summary: null,
  version: 3,
  links: [contact, project],
};

function renderCard(props: Partial<Parameters<typeof EntryCard>[0]> = {}) {
  const onOpen = vi.fn();
  const view = render(
    <EntryCard
      entry={entry}
      today="2026-11-03"
      labels={journalEn}
      onOpen={onOpen}
      {...props}
    />,
  );
  return { ...view, onOpen };
}

describe("journal entry card: a contact name opens the contact", () => {
  it("opens the contact in fullscreen when its name is pressed", async () => {
    const user = userEvent.setup();
    const onOpenContact = vi.fn();
    renderCard({ onOpenContact });

    const name = screen.getByRole("button", { name: "Anna Andersson" });
    expect(name.tagName).toBe("BUTTON");
    expect(name).toHaveClass("journal-link-name");
    await user.click(name);

    expect(onOpenContact).toHaveBeenCalledTimes(1);
    expect(onOpenContact).toHaveBeenCalledWith(contact);
  });

  it("keeps the links as one line of text, with the contact name as the button in it", () => {
    const { container } = renderCard({ onOpenContact: vi.fn() });

    const line = container.querySelector("p.journal-card-links");
    expect(line).not.toBeNull();
    expect(line?.textContent).toBe("Linked to Anna Andersson and Köket");
    expect(line?.querySelector("button.journal-link-name")?.textContent).toBe(
      "Anna Andersson",
    );
  });

  it("keeps the project name as plain text, not a button", () => {
    renderCard({ onOpenContact: vi.fn() });

    const projectName = screen.getByText("Köket");
    expect(projectName.tagName).toBe("SPAN");
    expect(projectName).toHaveClass("journal-link-name");
    expect(screen.queryByRole("button", { name: "Köket" })).toBeNull();
  });

  it("without onOpenContact the contact name is a plain span, not a button", () => {
    renderCard();

    expect(screen.getByText("Anna Andersson").tagName).toBe("SPAN");
    expect(screen.queryByRole("button", { name: "Anna Andersson" })).toBeNull();
  });

  it("the card has no remove buttons: a link is removed in the entry's fullscreen view", () => {
    const { container } = renderCard({ onOpenContact: vi.fn() });

    expect(
      screen.queryByRole("button", { name: /Remove link/ }),
    ).not.toBeInTheDocument();
    expect(container.querySelector(".journal-chip")).toBeNull();
    expect(container.querySelector(".journal-chip-remove")).toBeNull();
  });
});
