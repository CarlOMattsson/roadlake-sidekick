import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "@/features/work-app/inline/inline-summary-labels";
import {
  InlineSummary,
  type InlineSummaryData,
} from "@/features/work-app/inline/inline-summary";
import { KnownTags } from "@/features/work-app/shared/work-tags";
import { installFixedClock } from "./helpers/inline-summary-fixtures";

installFixedClock();

const task: InlineSummaryData = {
  kind: "task",
  title: "Ring Anna om offerten",
  status: "in_progress",
  dueDate: "2026-10-30T09:00:00Z",
};

const project: InlineSummaryData = {
  kind: "project",
  title: "Sommarfest",
  status: "active",
  dueDate: "2026-11-15",
};

function pills(container: HTMLElement): string[] {
  return Array.from(container.querySelectorAll(".sk-tag")).map(
    (pill) => pill.textContent ?? "",
  );
}

describe("InlineSummary tags", () => {
  it.each([
    ["task", task],
    ["project", project],
  ])("shows two tags and +N on the %s card", (_name, summary) => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...summary, tags: ["viktig", "familj", "resa", "mat"] }}
      />,
    );
    expect(pills(container)).toEqual(["viktig", "familj", "+2"]);
  });

  it("shows no +N when the tags fit and no line at all without tags", () => {
    const { container, rerender } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsEn}
        summary={{ ...task, tags: ["viktig", "familj"] }}
      />,
    );
    expect(pills(container)).toEqual(["viktig", "familj"]);
    for (const tags of [undefined, []]) {
      rerender(
        <InlineSummary
          state="ready"
          labels={inlineSummaryLabelsEn}
          summary={{ ...task, tags }}
        />,
      );
      expect(container.querySelector(".sk-tags")).toBeNull();
      expect(container.querySelector(".work-compact-tags")).toBeNull();
    }
  });

  it("reads the labels from the vocabulary when the card has it, the slug otherwise", () => {
    const { container } = render(
      <KnownTags.Provider
        value={[{ slug: "viktig", label: "Viktigt", count: 3 }]}
      >
        <InlineSummary
          state="ready"
          labels={inlineSummaryLabelsSv}
          summary={{ ...task, tags: ["viktig", "familj"] }}
        />
      </KnownTags.Provider>,
    );
    expect(pills(container)).toEqual(["Viktigt", "familj"]);
  });

  it("reads the tags once as a sentence in the card's language", () => {
    const { container } = render(
      <InlineSummary
        state="ready"
        labels={inlineSummaryLabelsSv}
        summary={{ ...project, tags: ["a", "b", "c"] }}
      />,
    );
    expect(container.querySelector(".sk-tags-sr")).toHaveTextContent(
      "Taggar: a, b och 1 till",
    );
  });
});
