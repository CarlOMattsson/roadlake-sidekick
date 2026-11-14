import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { JournalView } from "@/features/journal-app/journal-view";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import {
  draftRoot,
  OFFERTEN,
  renderDraft,
  transportMock,
} from "@tests/helpers/journal-app-fixtures";

function follows(a: Element, b: Element): boolean {
  return Boolean(
    a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING,
  );
}

describe("the draft's reading order", () => {
  it("fullscreen puts Edit right under the summary, before the Tags section", async () => {
    render(
      <JournalView
        transport={transportMock()}
        initial={draftRoot}
        labels={journalEn}
        fullscreen
      />,
    );
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const edit = screen.getByRole("button", { name: "Edit" });
    const tags = screen.getByRole("heading", { name: journalEn.draftTags });
    const summary = screen.getByText("Kunden vill ha offerten före fredag.");
    expect(follows(summary, edit)).toBe(true);
    expect(follows(edit, tags)).toBe(true);
  });

  it("inline keeps the tag field on the summary's row, above Edit", async () => {
    renderDraft(transportMock());
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const add = screen.getByRole("button", { name: "Add tag" });
    expect(follows(add, screen.getByRole("button", { name: "Edit" }))).toBe(
      true,
    );
  });
});

describe("the draft's header", () => {
  it("names the day on the Claude's draft line and keeps the note on a line of its own", async () => {
    renderDraft(transportMock());
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const line = screen.getByText(journalEn.aiDraft).closest("p");
    expect(line?.textContent).toMatch(/^Claude’s draft · \d{1,2} \w+/);
    const note = screen.getByText(journalEn.draftNote);
    expect(note.closest("p")).not.toBe(line);
  });

  it("reads in Swedish, with no dangling pronoun", async () => {
    renderDraft(transportMock(), journalSv);
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    expect(
      screen.getByText(journalSv.aiDraft).closest("p")?.textContent,
    ).toMatch(/^Claudes utkast · \d{1,2} \p{L}+/u);
    expect(
      screen.getByText(
        "Inget sparas förrän du sparar utkastet som anteckning.",
      ),
    ).toBeVisible();
  });
});

describe("suggested links and the owner's own candidates", () => {
  it("tells which list the checkboxes belong to, once, between the two kinds", async () => {
    renderDraft(transportMock());
    await screen.findByRole("heading", { level: 2, name: OFFERTEN });
    const lead = screen.getAllByText(journalEn.otherCandidates);
    // Only Contacts mixes a suggestion (Anna) with a candidate Claude did not suggest (Bo).
    expect(lead).toHaveLength(1);
    const anna = screen.getByRole("group", {
      name: "Decision for Anna Andersson",
    });
    const bo = screen.getByRole("checkbox", { name: "Bo Berg" });
    expect(follows(anna, lead[0]!)).toBe(true);
    expect(follows(lead[0]!, bo)).toBe(true);
  });
});

describe("texts that say what is saved", () => {
  it("name the thing that is saved instead of 'it'", () => {
    for (const labels of [journalEn, journalSv]) {
      expect(labels.tellClaudeHint).not.toMatch(/\b(saves it|sparar det)\b/);
      expect(labels.pendingNote).not.toMatch(/\b(save it|sparar det)\b/);
    }
    expect(journalSv.pendingNote).toContain("sparar utkastet");
    expect(journalEn.pendingNote).toContain("save the draft");
    expect(journalSv.tellClaudeHint).toContain("dina svar");
    expect(journalEn.tellClaudeHint).toContain("your answers");
  });
});
