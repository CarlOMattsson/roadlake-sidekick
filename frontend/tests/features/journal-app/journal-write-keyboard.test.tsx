import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { EntryTextForm } from "@/features/journal-app/entry-write";
import { journalSv } from "@/features/journal-app/labels";

function form(kind: "new" | "append") {
  return (
    <EntryTextForm
      labels={journalSv}
      kind={kind}
      signatureBase="2026-10-24"
      submit={vi.fn().mockResolvedValue(undefined)}
      onCancel={vi.fn()}
    />
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  Reflect.deleteProperty(document, "scrollingElement");
});

describe("the write form and the on-screen keyboard", () => {
  it("focuses the title without the browser's own scroll and starts at the top of the page", () => {
    // jsdom has no scrolling element: a plain object stands in for the page's.
    const root = { scrollTop: 240 };
    Object.defineProperty(document, "scrollingElement", {
      value: root,
      configurable: true,
    });
    const focus = vi.spyOn(HTMLElement.prototype, "focus");
    render(form("new"));
    expect(screen.getByLabelText(journalSv.titleLabel)).toHaveFocus();
    expect(focus).toHaveBeenCalledWith({ preventScroll: true });
    expect(root.scrollTop).toBe(0);
  });

  it("focuses the text of an appended entry", () => {
    render(form("append"));
    expect(screen.getByLabelText(journalSv.appendTextLabel)).toHaveFocus();
  });

  it("brings the focused field back into view when the keyboard resizes the window", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(form("new"));
    scroll.mockClear();
    window.dispatchEvent(new Event("resize"));
    expect(scroll).toHaveBeenCalledWith({ block: "nearest" });
  });

  it("leaves a field outside the form alone on resize", () => {
    const scroll = vi.fn();
    Element.prototype.scrollIntoView = scroll;
    render(
      <>
        <button type="button">outside</button>
        {form("new")}
      </>,
    );
    screen.getByRole("button", { name: "outside" }).focus();
    scroll.mockClear();
    window.dispatchEvent(new Event("resize"));
    expect(scroll).not.toHaveBeenCalled();
  });
});
