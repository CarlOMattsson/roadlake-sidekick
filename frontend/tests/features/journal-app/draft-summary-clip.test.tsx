import { render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { DraftSummary } from "@/features/journal-app/draft-review-parts/draft-summary";
import { journalSv } from "@/features/journal-app/labels";

const TEXT = "Kunden vill ha offerten före fredag. Ingen garanti. Ring upp.";

// jsdom does no layout: a paragraph "fits" when it holds at most `limit` characters.
function fakeLayout(limit: number) {
  vi.spyOn(Element.prototype, "scrollHeight", "get").mockImplementation(
    function (this: Element) {
      return (this.textContent?.length ?? 0) > limit ? 100 : 20;
    },
  );
  vi.spyOn(Element.prototype, "clientHeight", "get").mockReturnValue(20);
}

afterEach(() => vi.restoreAllMocks());

describe("DraftSummary clipping", () => {
  it("cuts a long text at a word, drops the punctuation, and offers Läs mer", () => {
    fakeLayout(40);
    const { container } = render(
      <DraftSummary text={TEXT} labels={journalSv} />,
    );
    expect(container.querySelector("p span[aria-hidden]")?.textContent).toBe(
      "Kunden vill ha offerten före fredag…",
    );
    expect(
      container.querySelector(".journal-visually-hidden")?.textContent,
    ).toBe(TEXT);
    expect(
      screen.getByRole("button", { name: journalSv.readMore }),
    ).toBeInTheDocument();
  });

  it("shows a short text whole with no toggle", () => {
    fakeLayout(400);
    const { container } = render(
      <DraftSummary text={TEXT} labels={journalSv} />,
    );
    expect(container.querySelector("p")?.textContent).toBe(TEXT);
    expect(container.querySelector("[aria-hidden]")).toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });
});
