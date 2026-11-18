import { render, screen } from "@testing-library/react";
import { expect, it } from "vitest";
import { aiStepEn, aiStepSv } from "@/features/mcp-apps/ui/ai-step-labels";
import { AiStepMark, waitsForOwner } from "@/features/mcp-apps/ui/ai-step-mark";

it("keeps the English words to the same keys as the Swedish", () => {
  expect(Object.keys(aiStepEn.performer)).toEqual(
    Object.keys(aiStepSv.performer),
  );
  expect(Object.keys(aiStepEn.status)).toEqual(Object.keys(aiStepSv.status));
});

it("marks an owner Step with Du and an AI Step with AI and where it stands", () => {
  const { rerender } = render(
    <AiStepMark performer="owner" state={null} locale="sv-SE" />,
  );
  expect(screen.getByRole("img", { name: "Görs av dig" })).toHaveTextContent(
    "Du",
  );
  rerender(<AiStepMark performer="ai" state="ready" locale="sv-SE" />);
  expect(
    screen.getByRole("img", { name: "Görs av AI, redo" }),
  ).toHaveTextContent("AI · redo");
});

it("says that an AI Step is to be reviewed or has a question, as the owner's attention", () => {
  const { rerender } = render(
    <AiStepMark performer="ai" state="to_review" locale="sv-SE" />,
  );
  const mark = screen.getByRole("img", { name: "Görs av AI, att granska" });
  expect(mark).toHaveTextContent("AI · att granska");
  expect(mark).toHaveAttribute("data-attention", "true");
  rerender(<AiStepMark performer="ai" state="needs_input" locale="sv-SE" />);
  expect(screen.getByRole("img")).toHaveTextContent("AI · fråga");
  rerender(<AiStepMark performer="ai" state="running" locale="sv-SE" />);
  expect(screen.getByRole("img")).not.toHaveAttribute("data-attention");
});

it("reads in English for an English locale", () => {
  const { rerender } = render(
    <AiStepMark performer="owner" state={null} locale="en-GB" />,
  );
  expect(
    screen.getByRole("img", { name: "Performed by you" }),
  ).toHaveTextContent("You");
  rerender(<AiStepMark performer="ai" state="to_review" locale="en-GB" />);
  expect(
    screen.getByRole("img", { name: "Performed by AI, to review" }),
  ).toHaveTextContent("AI · to review");
});

it("names no state for a done AI Step and draws nothing for a Step without a performer", () => {
  const { container, rerender } = render(
    <AiStepMark performer="ai" state="done" locale="sv-SE" />,
  );
  expect(screen.getByRole("img")).toHaveTextContent(/^AI$/);
  rerender(<AiStepMark performer={undefined} locale="sv-SE" />);
  expect(container).toBeEmptyDOMElement();
});

it("treats only a result to review or a question as waiting for the owner", () => {
  expect(waitsForOwner("to_review")).toBe(true);
  expect(waitsForOwner("needs_input")).toBe(true);
  for (const state of [
    "waiting",
    "ready",
    "running",
    "failed",
    "stopped",
    "exhausted",
    "done",
    null,
    undefined,
  ] as const) {
    expect(waitsForOwner(state)).toBe(false);
  }
});
