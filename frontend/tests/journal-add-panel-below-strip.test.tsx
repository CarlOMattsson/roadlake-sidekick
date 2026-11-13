// The Dagbok + panel opens under the week strip, where the day's content starts, so the strip never moves.
// The dark button names what it does: it hands over to Claude. Simulated-host test (JournalView with a mocked transport).
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import { journalEn, journalSv } from "@/features/journal-app/labels";
import { JournalView } from "@/features/journal-app/journal-view";
import { dayRoot, transportMock } from "./helpers/journal-app-fixtures";

function open(labels: typeof journalEn) {
  const writeEntry = vi.fn();
  render(
    <JournalView
      transport={transportMock({ writeEntry })}
      initial={dayRoot}
      labels={labels}
      fullscreen
      onTellClaude={vi.fn()}
    />,
  );
}

describe("Dagbok + panel", () => {
  it("opens after the week strip, not between the date row and the strip, and is not in the page while closed", async () => {
    const user = userEvent.setup();
    open(journalEn);
    const strip = document.querySelector(".sk-day-strip")!;
    expect(document.querySelector(".journal-add-panel")).toBeNull();
    const add = screen.getByRole("button", { name: journalEn.addEntry });
    expect(add).not.toHaveAttribute("aria-controls");
    await user.click(add);
    const panel = document.querySelector(".journal-add-panel")!;
    expect(panel).not.toBeNull();
    expect(add).toHaveAttribute("aria-controls", panel.id);
    // The strip stays where it was, right under the date head; the panel follows it.
    expect(strip.previousElementSibling).toHaveClass("sk-day-strip-head");
    expect(
      strip.compareDocumentPosition(panel) & Node.DOCUMENT_POSITION_FOLLOWING,
    ).toBeTruthy();
    // Escape, from inside the panel, closes it and returns to +.
    panel.querySelector("button")!.focus();
    await user.keyboard("{Escape}");
    expect(document.querySelector(".journal-add-panel")).toBeNull();
    expect(add).toHaveFocus();
  });

  it.each([
    [journalEn, "Tell Claude about the day"],
    [journalSv, "Berätta för Claude om dagen"],
  ] as const)(
    "names the dark button for the hand-over to Claude (%#)",
    async (labels, name) => {
      const user = userEvent.setup();
      open(labels);
      await user.click(screen.getByRole("button", { name: labels.addEntry }));
      const panel = document.querySelector<HTMLElement>(".journal-add-panel")!;
      expect(panel.querySelector(".sk-btn--primary")).toHaveTextContent(name);
      expect(labels.tellClaude).toBe(name);
    },
  );
});
