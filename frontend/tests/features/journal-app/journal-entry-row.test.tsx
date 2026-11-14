import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  EntryRow,
  type EntryRowData,
  type EntryRowProps,
} from "@/features/journal-app/entry-row";
import { journalEn, journalSv } from "@/features/journal-app/labels";

// No time zone offset, so the time is the same local clock time in every environment.
const ENTRY: EntryRowData = {
  id: "entry-1",
  source_id: "source-1",
  title: "Promenad med Bo",
  summary: "Pratade om huset och flytten.",
  occurred_at: "2026-10-24T09:10:00",
  contact_ids: ["c1", "c2"],
  task_ids: ["t1"],
};

function renderRow(
  overrides: Partial<EntryRowProps> = {},
  labels = journalSv,
  entry: Partial<EntryRowData> = {},
) {
  const props: EntryRowProps = {
    entry: { ...ENTRY, ...entry },
    labels,
    ...overrides,
  };
  render(
    <ul>
      <EntryRow {...props} />
    </ul>,
  );
  return { props };
}

describe("EntryRow", () => {
  it("is one row in the timeline, with the title and the two-line excerpt", () => {
    renderRow();
    const row = document.querySelector("li.journal-entry-row");
    expect(row).not.toBeNull();
    expect(row?.querySelectorAll(".journal-entry-card")).toHaveLength(1);
    expect(row?.querySelector("time")?.getAttribute("datetime")).toBe(
      ENTRY.occurred_at,
    );
    expect(screen.getByText("Promenad med Bo")).toBeInTheDocument();
    // The two-line clamp is in journal.css, so the excerpt carries its class and no inline style.
    const excerpt = screen.getByText("Pratade om huset och flytten.");
    expect(excerpt).toHaveClass("journal-entry-excerpt");
    expect(excerpt).not.toHaveAttribute("style");
  });

  it("puts the title first and the time and the link counts on one grey line under it", () => {
    renderRow();
    const meta = document.querySelector(".journal-entry-meta");
    expect(meta?.textContent).toBe("09:10 · 2 kontakter · 1 uppgift");
    const title = screen.getByText("Promenad med Bo");
    expect(
      title.compareDocumentPosition(meta!) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).not.toBe(0);
  });

  it("names the linked contacts and projects instead of the contact count, two at most and then the rest", () => {
    renderRow({}, journalSv, {
      links: [
        { kind: "contact", id: "c1", label: "Anna Andersson" },
        { kind: "project", id: "p1", label: "Köket" },
        { kind: "contact", id: "c2", label: "Lars Ek" },
      ],
    });
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10 · Anna Andersson, Köket och 1 fler · 1 uppgift",
    );
  });

  it("names two links with a comma and no count of the rest", () => {
    renderRow({}, journalSv, {
      links: [
        { kind: "contact", id: "c1", label: "Anna Andersson" },
        { kind: "project", id: "p1", label: "Köket" },
      ],
    });
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10 · Anna Andersson, Köket · 1 uppgift",
    );
  });

  it("shows no contact count when the result carries links, even an empty list", () => {
    renderRow({}, journalSv, { links: [], task_ids: [] });
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10",
    );
  });

  it("puts the archived marker before the linked names", () => {
    renderRow({}, journalEn, {
      archived: true,
      links: [{ kind: "contact", id: "c1", label: "Anna Andersson" }],
    });
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10 · Archived · Anna Andersson · 1 task",
    );
  });

  it("omits the link counts that are zero and the summary when it is missing", () => {
    renderRow({}, journalSv, {
      contact_ids: [],
      task_ids: ["t1"],
      summary: null,
    });
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10 · 1 uppgift",
    );
    expect(screen.queryByText(/kontakt/)).toBeNull();
    expect(screen.queryByText("Pratade om huset och flytten.")).toBeNull();
  });

  it("shows no original toggle and no original region: the entry view reads the original", () => {
    renderRow();
    expect(
      screen.queryByRole("button", { name: journalSv.showOriginal }),
    ).toBeNull();
    expect(screen.queryByRole("region")).toBeNull();
    expect(screen.queryByRole("status")).toBeNull();
  });

  it("opens the entry from the card button and shows a chevron only then", async () => {
    const user = userEvent.setup();
    const onOpen = vi.fn();
    renderRow({ onOpen });
    const card = screen.getByText("Promenad med Bo").closest("button");
    expect(card).toHaveClass("journal-entry-card");
    expect(
      document
        .querySelector("li.journal-entry-row")
        ?.getAttribute("data-navigates"),
    ).toBe("true");
    const chevron = card?.querySelector(".journal-entry-chevron");
    expect(chevron?.querySelector("svg")).not.toBeNull();
    await user.click(card as HTMLElement);
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("renders the card as plain content without onOpen", () => {
    renderRow();
    expect(screen.getByText("Promenad med Bo").closest("button")).toBeNull();
    expect(
      document
        .querySelector("li.journal-entry-row")
        ?.hasAttribute("data-navigates"),
    ).toBe(false);
    expect(document.querySelector(".journal-entry-chevron")).toBeNull();
  });

  it("labels the counts in English", () => {
    renderRow({}, journalEn);
    expect(document.querySelector(".journal-entry-meta")?.textContent).toBe(
      "09:10 · 2 contacts · 1 task",
    );
  });
});

describe("how many tags a row names", () => {
  const tags = ["kund", "viktig", "familj", "hus", "resa"];

  function withWidth(width: number) {
    const before = window.innerWidth;
    Object.defineProperty(window, "innerWidth", {
      value: width,
      configurable: true,
    });
    return () =>
      Object.defineProperty(window, "innerWidth", {
        value: before,
        configurable: true,
      });
  }

  it("names two and counts the rest on a phone", () => {
    const restore = withWidth(375);
    renderRow({}, journalEn, { tags });
    restore();
    expect(screen.getByText("+3")).toBeInTheDocument();
  });

  it("names four on a wide frame", () => {
    const restore = withWidth(1280);
    renderRow({}, journalEn, { tags });
    restore();
    expect(screen.getByText("+1")).toBeInTheDocument();
  });
});
