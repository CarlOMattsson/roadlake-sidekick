import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { insightEn, insightSv } from "@/features/mcp-apps/ui/insight-labels";
import { InsightLine } from "@/features/mcp-apps/ui/insight-line";

const LONG =
  "Du sov dåligt i natt, så den tunga uppgiften om hyresavtalet flyttades till imorgon förmiddag, när du brukar ha mest ork kvar.";
const SHORT = "Sedan i fredags: 6 körningar.";

// jsdom does no layout: a box "holds" its text when the text has at most `limit` characters (two lines' worth).
function fakeLayout(limit: number) {
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(
    function (this: Element) {
      return (this.textContent?.length ?? 0) > limit ? 100 : 48;
    },
  );
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(48);
}

afterEach(() => vi.restoreAllMocks());

const text = (container: HTMLElement) =>
  container.querySelector(".sk-insight__text");

describe("InsightLine", () => {
  it("cuts a long sentence at a word in a list, and keeps it whole for a screen reader", () => {
    fakeLayout(60);
    const { container } = render(
      <InsightLine text={LONG} locale="sv-SE" onMore={() => undefined} />,
    );
    const p = text(container);
    expect(p?.tagName).toBe("P");
    expect(p).toHaveAttribute("data-clamped");
    const drawn = p?.querySelector("[aria-hidden]")?.textContent ?? "";
    expect(drawn).toBe("Du sov dåligt i natt, så den tunga uppgiften om…");
    expect(LONG.startsWith(drawn.slice(0, -1))).toBe(true);
    expect(p?.querySelector(".sk-insight__whole")).toHaveTextContent(LONG);
    expect(container.querySelector("h1, h2, h3, h4")).toBeNull();
  });

  it("shows the sentence whole in the detail view, without a button", () => {
    fakeLayout(60);
    const { container } = render(
      <InsightLine
        text={LONG}
        locale="sv-SE"
        density="detail"
        onMore={() => undefined}
      />,
    );
    expect(text(container)).not.toHaveAttribute("data-clamped");
    expect(text(container)?.textContent).toBe(LONG);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("in an inline card keeps the two lines and adds no button, since the card's link row leads on", () => {
    fakeLayout(60);
    const { container } = render(
      <InsightLine
        text={LONG}
        locale="sv-SE"
        density="inline"
        onMore={() => undefined}
      />,
    );
    expect(text(container)).toHaveAttribute("data-clamped");
    expect(container.querySelector("[aria-hidden]")).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("draws nothing without a sentence", () => {
    const { container } = render(<InsightLine text="  " locale="sv-SE" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("opens the view that says more with Show more ›, in the room's language", () => {
    fakeLayout(400);
    const onMore = vi.fn();
    const { rerender } = render(
      <InsightLine text={SHORT} locale="sv-SE" onMore={onMore} />,
    );
    const more = screen.getByRole("button", { name: "Visa mer" });
    expect(more.querySelector("svg")).toHaveAttribute("aria-hidden", "true");
    expect(more).not.toHaveAttribute("aria-expanded");
    fireEvent.click(more);
    expect(onMore).toHaveBeenCalledTimes(1);

    rerender(<InsightLine text={SHORT} locale="en-GB" onMore={onMore} />);
    expect(screen.getByRole("button", { name: "Show more" })).toBeVisible();
  });

  it("without a view to open, opens a cut sentence in place and closes it again, without ›", () => {
    fakeLayout(60);
    const { container } = render(<InsightLine text={LONG} locale="sv-SE" />);
    const toggle = screen.getByRole("button", { name: "Visa mer" });
    expect(toggle.querySelector("svg")).toBeNull();
    expect(toggle).toHaveAttribute("aria-expanded", "false");
    fireEvent.click(toggle);
    const less = screen.getByRole("button", { name: "Visa mindre" });
    expect(less).toHaveAttribute("aria-expanded", "true");
    expect(text(container)).not.toHaveAttribute("data-clamped");
    expect(text(container)?.textContent).toBe(LONG);
    fireEvent.click(less);
    expect(text(container)).toHaveAttribute("data-clamped");
    expect(screen.getByRole("button", { name: "Visa mer" })).toHaveAttribute(
      "aria-expanded",
      "false",
    );
  });

  it("offers nothing for a sentence the two lines hold", () => {
    fakeLayout(400);
    const { container } = render(<InsightLine text={LONG} locale="en-GB" />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(text(container)?.textContent).toBe(LONG);
  });

  it("has the same keys in Swedish and English", () => {
    expect(Object.keys(insightSv).sort()).toEqual(
      Object.keys(insightEn).sort(),
    );
    for (const value of Object.values(insightSv)) expect(value).not.toBe("");
  });
});
