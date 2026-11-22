import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  FlipCard,
  isDrawablePhoto,
  type FlipCardProps,
} from "@/features/mcp-apps/ui/flip-card";
import {
  reviewEn,
  reviewLabelsFor,
  reviewSv,
} from "@/features/mcp-apps/ui/review-labels";

const PHOTO = "data:image/png;base64,iVBORw0KGgo=";

function keysOf(value: unknown, prefix = ""): string[] {
  if (typeof value !== "object" || value === null) return [prefix];
  return Object.entries(value).flatMap(([key, inner]) =>
    keysOf(inner, prefix ? `${prefix}.${key}` : key),
  );
}

function leaves(value: unknown): unknown[] {
  if (typeof value !== "object" || value === null) return [value];
  return Object.values(value).flatMap(leaves);
}

function setup(overrides: Partial<FlipCardProps> = {}) {
  const again = vi.fn();
  const good = vi.fn();
  const onReveal = vi.fn();
  const props: FlipCardProps = {
    locale: "sv-SE",
    front: {
      photo: { src: PHOTO, alt: "Foto att känna igen" },
      text: "Vem är det här?",
    },
    back: { title: "Lena Holm", meta: "Projektledare · Holm Bygg" },
    revealed: false,
    onReveal,
    grades: [
      { label: "Igen", onChoose: again },
      { label: "Kunde", onChoose: good, primary: true },
    ],
    ...overrides,
  };
  const view = render(<FlipCard {...props} />);
  const rerender = (next: Partial<FlipCardProps>) =>
    view.rerender(<FlipCard {...props} {...next} />);
  return { ...view, again, good, onReveal, props, rerender };
}

describe("review labels", () => {
  it("have the same keys in sv and en, none empty, and Swedish is the default", () => {
    expect(keysOf(reviewSv)).toEqual(keysOf(reviewEn));
    for (const text of [...leaves(reviewSv), ...leaves(reviewEn)])
      expect(String(text).trim()).not.toBe("");
    expect(reviewLabelsFor("en-GB")).toBe(reviewEn);
    expect(reviewLabelsFor("sv-SE")).toBe(reviewSv);
    expect(reviewLabelsFor("de-DE")).toBe(reviewSv);
  });
});

describe.each([
  { locale: "sv-SE", labels: reviewSv },
  { locale: "en-GB", labels: reviewEn },
])("FlipCard ($locale)", ({ locale, labels }) => {
  it("shows the face, the prompt and the reveal; the answer and the grades are hidden and inert", () => {
    const { container } = setup({ locale });

    expect(screen.getByRole("group", { name: labels.card })).toBeVisible();
    expect(
      screen.getByRole("img", { name: "Foto att känna igen" }),
    ).toHaveAttribute("src", PHOTO);
    expect(screen.getByText("Vem är det här?")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: labels.reveal }),
    ).toBeInTheDocument();
    expect(
      screen.queryByRole("button", { name: "Kunde" }),
    ).not.toBeInTheDocument();
    const back = container.querySelector(".sk-flip__side--back");
    expect(back).toHaveAttribute("aria-hidden", "true");
    expect(back).toHaveAttribute("inert");
  });

  it("a press on the reveal asks to turn, and the turn moves the focus to the answer, read with its lead", async () => {
    const user = userEvent.setup();
    const { onReveal, rerender, container } = setup({ locale });

    await user.click(screen.getByRole("button", { name: labels.reveal }));
    expect(onReveal).toHaveBeenCalledTimes(1);
    rerender({ revealed: true });

    const answer = container.querySelector(".sk-flip__answer");
    expect(answer).toHaveFocus();
    expect(answer).toHaveTextContent(`${labels.answer} Lena Holm`);
    expect(screen.getByText("Projektledare · Holm Bygg")).toBeVisible();
    expect(
      container.querySelector(".sk-flip__prompt")?.parentElement,
    ).toHaveAttribute("aria-hidden", "true");
    expect(
      screen.queryByRole("button", { name: labels.reveal }),
    ).not.toBeInTheDocument();
    expect(
      screen.getByRole("group", { name: labels.grades }),
    ).toBeInTheDocument();
  });

  it("Space and Enter in the card turn it; Space on the reveal button turns it once", async () => {
    const user = userEvent.setup();
    const { onReveal } = setup({ locale });

    screen.getByRole("group", { name: labels.card }).focus();
    await user.keyboard(" ");
    expect(onReveal).toHaveBeenCalledTimes(1);
    await user.keyboard("{Enter}");
    expect(onReveal).toHaveBeenCalledTimes(2);

    screen.getByRole("button", { name: labels.reveal }).focus();
    await user.keyboard(" ");
    expect(onReveal).toHaveBeenCalledTimes(3);
  });

  it("1 and 2 choose the grades once the card is turned, and the next card takes the focus to its reveal", async () => {
    const user = userEvent.setup();
    const { again, good, rerender } = setup({ locale });

    screen.getByRole("group", { name: labels.card }).focus();
    await user.keyboard("12");
    expect(again).not.toHaveBeenCalled();
    expect(good).not.toHaveBeenCalled();

    rerender({ revealed: true });
    screen.getByRole("group", { name: labels.card }).focus();
    await user.keyboard("1");
    expect(again).toHaveBeenCalledTimes(1);
    await user.keyboard("2");
    expect(good).toHaveBeenCalledTimes(1);
    await user.keyboard("3");
    await user.keyboard("{Control>}1{/Control}");
    expect(again).toHaveBeenCalledTimes(1);

    rerender({
      revealed: false,
      back: { title: "Omar Said", meta: "Elektriker" },
    });
    expect(screen.getByRole("button", { name: labels.reveal })).toHaveFocus();
  });

  it("the grade buttons name their keys, and fullscreen draws the reveal and Kunde as primary", () => {
    const { rerender } = setup({ locale, revealed: true });

    const again = screen.getByRole("button", { name: "Igen" });
    const good = screen.getByRole("button", { name: "Kunde" });
    expect(again).toHaveAttribute("aria-keyshortcuts", "1");
    expect(good).toHaveAttribute("aria-keyshortcuts", "2");
    expect(good).toHaveClass("sk-btn--primary");
    expect(again).toHaveClass("sk-btn--secondary");

    rerender({ revealed: false });
    expect(screen.getByRole("button", { name: labels.reveal })).toHaveClass(
      "sk-btn--primary",
    );
  });

  it("inline has no primary button and the smaller face", () => {
    const { container, rerender } = setup({ locale, density: "inline" });

    expect(container.querySelector(".sk-flip")).toHaveAttribute(
      "data-density",
      "inline",
    );
    expect(screen.getByRole("button", { name: labels.reveal })).toHaveClass(
      "sk-btn--secondary",
    );
    rerender({ revealed: true });
    expect(container.querySelectorAll(".sk-btn--primary")).toHaveLength(0);
  });

  it("while loading the face is a skeleton and the reveal is held but keeps the focus", async () => {
    const user = userEvent.setup();
    const { onReveal, container } = setup({ locale, loading: true });

    expect(screen.getByRole("group", { name: labels.card })).toHaveAttribute(
      "aria-busy",
      "true",
    );
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(container.querySelector(".sk-flip__skeleton")).toBeInTheDocument();
    const reveal = screen.getByRole("button", { name: labels.reveal });
    expect(reveal).toHaveAttribute("aria-disabled", "true");
    expect(reveal).not.toBeDisabled();
    await user.click(reveal);
    screen.getByRole("group", { name: labels.card }).focus();
    await user.keyboard(" ");
    expect(onReveal).not.toHaveBeenCalled();
  });

  it("while a grade is on its way the grades are held and keep the focus", async () => {
    const user = userEvent.setup();
    const { good } = setup({ locale, revealed: true, busy: true });

    const button = screen.getByRole("button", { name: "Kunde" });
    expect(button).toHaveAttribute("aria-disabled", "true");
    await user.click(button);
    expect(button).toHaveFocus();
    await user.keyboard("2");
    expect(good).not.toHaveBeenCalled();
  });

  it("shows a notice under the buttons", () => {
    setup({
      locale,
      revealed: true,
      notice: <p role="alert">Betyget kom inte fram</p>,
    });
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Betyget kom inte fram",
    );
  });
});

describe("FlipCard faces", () => {
  it("draws a question without a photo on the face, once", () => {
    const { container } = setup({
      front: { text: "Vad mäter en lux?" },
      back: { title: "Belysningsstyrka" },
    });
    expect(container.querySelector(".sk-flip__face--text")).toHaveTextContent(
      "Vad mäter en lux?",
    );
    expect(screen.getAllByText("Vad mäter en lux?")).toHaveLength(1);
    expect(container.querySelector(".sk-flip__prompt")).toBeNull();
  });

  it("draws only data: images, so the card never makes a request of its own", () => {
    expect(isDrawablePhoto(PHOTO)).toBe(true);
    expect(isDrawablePhoto("data:image/jpeg;base64,/9j/")).toBe(true);
    expect(isDrawablePhoto("https://example.com/face.png")).toBe(false);
    expect(isDrawablePhoto("data:image/svg+xml,<svg/>")).toBe(false);
    expect(isDrawablePhoto("blob:https://host/1")).toBe(false);

    setup({
      front: {
        photo: { src: "https://example.com/face.png", alt: "Foto" },
        text: "Vem är det här?",
      },
    });
    expect(screen.queryByRole("img")).not.toBeInTheDocument();
    expect(screen.getByText("Vem är det här?")).toBeInTheDocument();
  });

  it("a turn the view makes by itself does not pull the focus from elsewhere", () => {
    const outside = document.createElement("button");
    document.body.appendChild(outside);
    outside.focus();
    const { rerender, container } = setup();
    rerender({ revealed: true });
    expect(outside).toHaveFocus();
    expect(container.querySelector(".sk-flip__answer")).not.toHaveFocus();
    outside.remove();
  });
});
