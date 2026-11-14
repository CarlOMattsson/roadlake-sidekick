import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  cardLabelsEn,
  cardLabelsSv,
} from "@/features/work-app/shared/card-labels";
import { workEn, workSv } from "@/features/work-app/shared/labels";
import { WorkView } from "@/features/work-app/view/work-view";
import {
  rootFromToolResult,
  type WorkItemRecord,
  type WorkTransport,
} from "@/features/work-app/transport/transport";

function item(index: number): WorkItemRecord {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-00000000000${index}`,
    title: `Uppgift ${index}`,
    status: "todo",
    due_at: null,
    version: 1,
  };
}

/** A work_changes envelope as show_work_changes returns it, with seven Work records. */
const changes = {
  card: {
    kind: "work_changes",
    items: Array.from({ length: 7 }, (_, index) => item(index + 1)),
    total: 7,
    truncated: false,
  },
};

/** The card frames read nothing through the transport, so none of its methods is needed. */
const noReads = {} as WorkTransport;

describe("work_changes card frame", () => {
  it("opens as a card with the first five rows and +N for the rest", () => {
    const initial = rootFromToolResult(changes);
    render(
      <WorkView
        transport={noReads}
        initial={initial}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(5);
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("offers no Open action when the host has no fullscreen", () => {
    render(
      <WorkView
        transport={noReads}
        initial={rootFromToolResult(changes)}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    expect(screen.queryByRole("button", { name: "Show all (7)" })).toBeNull();
  });

  it("Show all asks the host for fullscreen", async () => {
    const fullscreen = vi.fn();
    render(
      <WorkView
        transport={noReads}
        initial={rootFromToolResult(changes)}
        labels={workEn}
        cardLabels={cardLabelsEn}
        fullscreen={fullscreen}
      />,
    );

    // The button names the whole list it opens: "Show all (7)".
    await userEvent.click(screen.getByRole("button", { name: "Show all (7)" }));
    expect(fullscreen).toHaveBeenCalledTimes(1);
  });

  it("uses the Swedish card labels for the host's Swedish locale", () => {
    render(
      <WorkView
        transport={noReads}
        initial={rootFromToolResult(changes)}
        labels={workEn}
        cardLabels={cardLabelsSv}
        fullscreen={vi.fn()}
      />,
    );

    // Seven Task records, all now To do: the headline says where they went.
    expect(screen.getByText("7 uppgifter, nu att göra")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Visa alla (7)" }),
    ).toBeInTheDocument();
  });
});

describe("error result", () => {
  it("opens the error card even when the result carries a card envelope", () => {
    // isError wins over the data: a failed call never shows the records it might carry.
    expect(rootFromToolResult(changes, true)).toEqual({ kind: "error" });
  });

  it("shows the shared error under the app's name and no Try again when the room gives none (the view alone cannot read anything again)", () => {
    render(
      <WorkView
        transport={noReads}
        initial={rootFromToolResult(undefined, true)}
        labels={workEn}
        cardLabels={cardLabelsEn}
      />,
    );

    // The card's overline is the app's name; the visually hidden h1 repeats it, so the card is searched.
    const card = screen.getByRole("alert").parentElement;
    expect(card?.querySelector(".sk-eyebrow")).toHaveTextContent(workEn.title);
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load your tasks",
    );
    expect(
      screen.queryByRole("button", { name: cardLabelsEn.retry }),
    ).toBeNull();
    expect(screen.queryByText(workEn.empty)).toBeNull();
  });

  it("names the app, not changes, in the Swedish error card when the result was not a change", () => {
    render(
      <WorkView
        transport={noReads}
        initial={rootFromToolResult(undefined, true)}
        labels={workSv}
        cardLabels={cardLabelsSv}
      />,
    );

    const alert = screen.getByRole("alert");
    expect(alert.parentElement?.querySelector(".sk-eyebrow")).toHaveTextContent(
      workSv.title,
    );
    expect(alert).toHaveTextContent("Uppgifterna kunde inte hämtas");
    expect(alert.textContent).not.toMatch(/ändringar/i);
    expect(
      screen.queryByRole("button", { name: cardLabelsSv.retry }),
    ).toBeNull();
  });
});
