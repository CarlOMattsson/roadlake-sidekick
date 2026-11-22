import { fireEvent, render, screen, within } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { DecisionCard } from "@/features/mcp-apps/ui/decision-card";
import {
  decisionEn,
  decisionLabelsFor,
  decisionSv,
} from "@/features/mcp-apps/ui/decision-labels";

function keysOf(value: object, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, inner]) =>
    inner && typeof inner === "object"
      ? keysOf(inner as object, `${prefix}${key}.`)
      : [`${prefix}${key}:${typeof inner}`],
  );
}

const base = {
  kicker: "Förslag",
  title: "Skapa kontakt: Lena Holm",
  changes: [
    { label: "Roll", value: "Projektledare" },
    { label: "E-post", value: "lena@example.com" },
    { label: "Företag", value: "Holm Bygg" },
  ],
  why: "Lena skrev under mejlet om köket.",
  source: { name: "Morgonmejl", at: "07:02" },
};

function actions() {
  return {
    approve: vi.fn(),
    dismiss: vi.fn(),
    review: vi.fn(),
    edit: vi.fn(),
  };
}

describe("decision labels", () => {
  it("keeps the English texts to the same keys and kinds as the Swedish", () => {
    expect(keysOf(decisionEn)).toEqual(keysOf(decisionSv));
  });

  it("picks English only for an English locale", () => {
    expect(decisionLabelsFor("en-GB")).toBe(decisionEn);
    expect(decisionLabelsFor("en")).toBe(decisionEn);
    expect(decisionLabelsFor("sv-SE")).toBe(decisionSv);
    expect(decisionLabelsFor("de")).toBe(decisionSv);
  });
});

describe("DecisionCard", () => {
  it("draws kicker with source, title, two changes and Varför inline, Avböj before Godkänn", () => {
    const run = actions();
    render(<DecisionCard locale="sv-SE" {...base} actions={run} />);
    const card = screen.getByRole("article", { name: base.title });
    expect(card).toHaveTextContent("Förslag · från Morgonmejl · 07:02");
    const items = within(card).getAllByRole("listitem");
    expect(items).toHaveLength(2);
    expect(items[1]).toHaveTextContent("E-post: lena@example.com +1");
    expect(within(items[1]!).getByLabelText("1 ändring till")).toBeVisible();
    expect(card).toHaveTextContent("Varför Lena skrev under mejlet om köket.");
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Avböj",
      "Godkänn",
    ]);
    expect(buttons[1]).toHaveClass("sk-btn--secondary", "sk-btn--compact");
    fireEvent.click(buttons[1]!);
    expect(run.approve).toHaveBeenCalledOnce();
    fireEvent.click(buttons[0]!);
    expect(run.dismiss).toHaveBeenCalledOnce();
    expect(screen.queryByRole("note")).toBeNull();
  });

  it("puts an unsure check first, with one change and no Varför inline", () => {
    render(
      <DecisionCard
        locale="sv-SE"
        {...base}
        trust={{ state: "unsure", reason: "Liknar en kontakt du redan har." }}
        actions={actions()}
      />,
    );
    const card = screen.getByRole("article");
    const note = within(card).getByRole("note");
    expect(card.firstElementChild).toBe(note);
    expect(note).toHaveTextContent(
      "Kontrollen var osäker: Liknar en kontakt du redan har.",
    );
    expect(within(card).getAllByRole("listitem")).toHaveLength(1);
    expect(card).not.toHaveTextContent("Varför");
    expect(
      within(card).getByRole("button", { name: "Godkänn" }),
    ).toBeInTheDocument();
  });

  it("offers no Approve on a suspicious card inline: Avböj, framed, and Granska", () => {
    const run = actions();
    render(
      <DecisionCard
        locale="sv-SE"
        {...base}
        trust={{
          state: "suspicious",
          reason: "Morgonmejl ska bara föreslå kontakter.",
        }}
        actions={run}
      />,
    );
    const card = screen.getByRole("article");
    expect(within(card).getByRole("note")).toHaveTextContent(
      "Misstänkt förslag",
    );
    expect(within(card).queryByRole("button", { name: /Godkänn/ })).toBeNull();
    // It cannot be approved here, so it shows no changes: the detail behind Granska has them all.
    expect(within(card).queryByRole("list")).toBeNull();
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Avböj",
      "Granska",
    ]);
    expect(buttons[0]).toHaveClass("sk-btn--secondary");
    fireEvent.click(buttons[1]!);
    expect(run.review).toHaveBeenCalledOnce();
    expect(run.approve).not.toHaveBeenCalled();
  });

  it("asks once before a suspicious detail approves, and takes the question back with Avbryt or Escape", () => {
    const run = actions();
    render(
      <DecisionCard
        locale="sv-SE"
        {...base}
        density="full"
        trust={{
          state: "suspicious",
          reason: "Morgonmejl ska bara föreslå kontakter.",
        }}
        actions={run}
      />,
    );
    const dismiss = screen.getByRole("button", { name: "Avböj" });
    expect(dismiss).toHaveClass("sk-btn--primary");
    fireEvent.click(screen.getByRole("button", { name: "Godkänn ändå" }));
    expect(run.approve).not.toHaveBeenCalled();
    const question = screen.getByRole("group", {
      name: "Godkänna ett misstänkt förslag?",
    });
    expect(
      within(question).getByRole("button", { name: "Avbryt" }),
    ).toHaveFocus();
    fireEvent.keyDown(question, { key: "Escape" });
    expect(screen.getByRole("button", { name: "Godkänn ändå" })).toHaveFocus();
    fireEvent.click(screen.getByRole("button", { name: "Godkänn ändå" }));
    fireEvent.click(
      within(
        screen.getByRole("group", { name: "Godkänna ett misstänkt förslag?" }),
      ).getByRole("button", { name: "Godkänn ändå" }),
    );
    expect(run.approve).toHaveBeenCalledOnce();
  });

  it("shows every change, before and after, the check and Ändra in full", () => {
    const run = actions();
    render(
      <DecisionCard
        locale="sv-SE"
        {...base}
        changes={[
          ...base.changes,
          { label: "Status", before: "Att göra", value: "Pågår" },
        ]}
        density="full"
        trust={{ state: "ok", confidence: 94 }}
        actions={run}
      >
        <p>Citat</p>
      </DecisionCard>,
    );
    const card = screen.getByRole("article");
    expect(within(card).getAllByRole("listitem")).toHaveLength(4);
    expect(within(card).getAllByRole("listitem")[3]).toHaveTextContent(
      "Status: Att göra → ändras till Pågår",
    );
    expect(card).toHaveTextContent("Kontrollerad · säker 94 %");
    expect(card).toHaveTextContent("Citat");
    const buttons = within(card).getAllByRole("button");
    expect(buttons.map((button) => button.textContent)).toEqual([
      "Ändra",
      "Avböj",
      "Godkänn",
    ]);
    expect(buttons[0]).toHaveAccessibleName("Ändra: Skapa kontakt: Lena Holm");
    expect(buttons[2]).toHaveClass("sk-btn--primary");
    fireEvent.click(buttons[0]!);
    expect(run.edit).toHaveBeenCalledOnce();
  });

  it("says Inte kontrollerad in full when the check did not run", () => {
    render(
      <DecisionCard
        locale="sv-SE"
        {...base}
        density="full"
        trust={{ state: "off" }}
        actions={actions()}
      />,
    );
    expect(screen.getByRole("article")).toHaveTextContent("Inte kontrollerad");
  });

  it("holds both answers while one runs, and keeps the card with the failure's line", () => {
    const run = actions();
    const { rerender } = render(
      <DecisionCard locale="sv-SE" {...base} busy="approve" actions={run} />,
    );
    const approving = screen.getByRole("button", { name: "Godkänner…" });
    expect(approving).toHaveAttribute("aria-busy", "true");
    fireEvent.click(approving);
    fireEvent.click(screen.getByRole("button", { name: "Avböj" }));
    expect(run.approve).not.toHaveBeenCalled();
    expect(run.dismiss).not.toHaveBeenCalled();
    rerender(
      <DecisionCard locale="sv-SE" {...base} failed="approve" actions={run} />,
    );
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Det gick inte att godkänna. Försök igen.",
    );
    expect(screen.getByRole("button", { name: "Godkänn" })).not.toHaveAttribute(
      "aria-disabled",
    );
  });

  it("turns into its receipt and keeps the undecided height while it holds", () => {
    const open = vi.fn();
    const height = vi
      .spyOn(HTMLElement.prototype, "getBoundingClientRect")
      .mockReturnValue({ height: 222 } as DOMRect);
    const { rerender } = render(
      <DecisionCard locale="sv-SE" {...base} actions={actions()} />,
    );
    rerender(
      <DecisionCard
        locale="sv-SE"
        {...base}
        actions={actions()}
        decided={{
          message: "Tillagd: Lena Holm",
          open: { label: "Öppna", onOpen: open },
          hold: true,
        }}
      />,
    );
    const card = screen.getByRole("article", { name: "Tillagd: Lena Holm" });
    expect(card).toHaveStyle({ minHeight: "222px" });
    expect(within(card).queryByRole("button", { name: "Godkänn" })).toBeNull();
    fireEvent.click(within(card).getByRole("button", { name: "Öppna" }));
    expect(open).toHaveBeenCalledOnce();
    rerender(
      <DecisionCard
        locale="sv-SE"
        {...base}
        actions={actions()}
        decided={{ message: "Tillagd: Lena Holm" }}
      />,
    );
    expect(screen.getByRole("article")).not.toHaveStyle({ minHeight: "222px" });
    height.mockRestore();
  });

  it("reads in English, and takes a ready conversation's own words for the answers", () => {
    render(
      <DecisionCard
        locale="en-GB"
        kicker="Ready conversation"
        title="Plan the week with Claude"
        why="You have four tasks without a date."
        source={{ name: "Morning mail" }}
        answerLabels={{ approve: "Start", dismiss: "Skip today" }}
        actions={actions()}
      />,
    );
    const card = screen.getByRole("article");
    expect(card).toHaveTextContent("Ready conversation · from Morning mail");
    expect(card).toHaveTextContent("Why You have four tasks without a date.");
    expect(
      within(card)
        .getAllByRole("button")
        .map((button) => button.textContent),
    ).toEqual(["Skip today", "Start"]);
  });
});
