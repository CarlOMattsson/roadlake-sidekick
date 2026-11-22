import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  QuestionCard,
  type QuestionCardProps,
} from "@/features/mcp-apps/ui/question-card";
import { reviewEn, reviewSv } from "@/features/mcp-apps/ui/review-labels";

const OPTIONS = ["Ljusflöde", "Belysningsstyrka", "Ljusstyrka", "Luminans"];

function setup(overrides: Partial<QuestionCardProps> = {}) {
  const onAnswer = vi.fn();
  const props: QuestionCardProps = {
    locale: "sv-SE",
    prompt: "Vad mäter en lux?",
    options: OPTIONS,
    onAnswer,
    ...overrides,
  };
  const view = render(<QuestionCard {...props} />);
  const rerender = (next: Partial<QuestionCardProps>) =>
    view.rerender(<QuestionCard {...props} {...next} />);
  return { ...view, onAnswer, rerender };
}

describe.each([
  { locale: "sv-SE", labels: reviewSv.question },
  { locale: "en-GB", labels: reviewEn.question },
])("QuestionCard ($locale)", ({ locale, labels }) => {
  it("is a group named by its prompt heading, with the options as buttons that name their keys", () => {
    setup({ locale });

    expect(
      screen.getByRole("heading", { level: 2, name: "Vad mäter en lux?" }),
    ).toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: "Vad mäter en lux?" }),
    ).toBeInTheDocument();
    const options = screen.getAllByRole("button");
    expect(options.map((button) => button.textContent)).toEqual(OPTIONS);
    expect(
      options.map((button) => button.getAttribute("aria-keyshortcuts")),
    ).toEqual(["1", "2", "3", "4"]);
    expect(
      screen.getByRole("group", { name: labels.options }),
    ).toBeInTheDocument();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("one press answers, and so does a number key", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup({ locale });

    await user.click(screen.getByRole("button", { name: "Belysningsstyrka" }));
    expect(onAnswer).toHaveBeenLastCalledWith(1);
    screen.getByRole("button", { name: "Ljusflöde" }).focus();
    await user.keyboard("3");
    expect(onAnswer).toHaveBeenLastCalledWith(2);
    await user.keyboard("5");
    await user.keyboard("{Alt>}1{/Alt}");
    expect(onAnswer).toHaveBeenCalledTimes(2);
  });

  it("the arrow keys move between the options", async () => {
    const user = userEvent.setup();
    setup({ locale });

    screen.getByRole("button", { name: "Ljusflöde" }).focus();
    await user.keyboard("{ArrowDown}");
    expect(
      screen.getByRole("button", { name: "Belysningsstyrka" }),
    ).toHaveFocus();
    await user.keyboard("{End}");
    expect(screen.getByRole("button", { name: "Luminans" })).toHaveFocus();
  });

  it("while the server checks, the sent row reads the check and every row is held but keeps the focus", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup({ locale, chosen: 1 });

    const sent = screen.getByRole("button", {
      name: `Belysningsstyrka ${labels.checking}`,
    });
    expect(sent).toHaveAttribute("aria-busy", "true");
    for (const button of screen.getAllByRole("button"))
      expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(sent);
    expect(sent).toHaveFocus();
    await user.keyboard("1");
    expect(onAnswer).not.toHaveBeenCalled();
  });

  it("a right answer says so with its reason, and Nästa moves the focus to the next question's first option", async () => {
    const user = userEvent.setup();
    const next = vi.fn();
    const { rerender, container } = setup({
      locale,
      chosen: 1,
      result: { correct: true, explain: "Lux är lumen per kvadratmeter." },
      action: { label: labels.next, onClick: next },
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      `${labels.correct} Lux är lumen per kvadratmeter.`,
    );
    expect(container.querySelector('[data-state="correct"]')).toHaveTextContent(
      "Belysningsstyrka",
    );
    await user.click(screen.getByRole("button", { name: labels.next }));
    expect(next).toHaveBeenCalledTimes(1);

    rerender({
      prompt: "Vad mäter en lumen?",
      options: ["Ljusflöde", "Ljusstyrka", "Luminans"],
      chosen: null,
      result: null,
      action: undefined,
    });
    expect(screen.getByRole("button", { name: "Ljusflöde" })).toHaveFocus();
    expect(screen.getByRole("status")).toBeEmptyDOMElement();
  });

  it("a wrong answer says Inte riktigt and offers the question again", async () => {
    const user = userEvent.setup();
    const retry = vi.fn();
    const { rerender, container } = setup({
      locale,
      chosen: 0,
      result: { correct: false, explain: "Det är lumen." },
      action: { label: labels.retry, onClick: retry },
    });

    expect(screen.getByRole("status")).toHaveTextContent(
      `${labels.wrong} Det är lumen.`,
    );
    expect(container.querySelector('[data-state="wrong"]')).toHaveTextContent(
      "Ljusflöde",
    );
    expect(container.querySelector('[data-state="correct"]')).toBeNull();
    await user.click(screen.getByRole("button", { name: labels.retry }));
    expect(retry).toHaveBeenCalledTimes(1);
    rerender({ chosen: null, result: null, action: undefined });
    expect(screen.getByRole("button", { name: "Ljusflöde" })).toHaveFocus();
    expect(
      screen.getByRole("button", { name: "Ljusflöde" }),
    ).not.toHaveAttribute("aria-disabled");
  });

  it("without a network the options are held and the reason is shown", async () => {
    const user = userEvent.setup();
    const { onAnswer } = setup({ locale, unavailable: "Kräver anslutning" });

    expect(screen.getByText("Kräver anslutning")).toBeInTheDocument();
    for (const button of screen.getAllByRole("button"))
      expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(screen.getByRole("button", { name: "Luminans" }));
    expect(onAnswer).not.toHaveBeenCalled();
  });
});
