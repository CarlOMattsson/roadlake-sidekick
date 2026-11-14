import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import {
  cardLabelsEn,
  cardLabelsFor,
  cardLabelsSv,
} from "@/features/work-app/shared/card-labels";
import { WorkCard } from "@/features/work-app/inline/work-card";
import type {
  WorkCardFrame,
  WorkItemRecord,
} from "@/features/work-app/transport/transport";

describe("work card counts", () => {
  it("states the same count in its title and on Show all, and no +N line beside Show all", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame(5, 11)}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("region")).toHaveAccessibleName("Ändringar (11)");
    expect(
      screen.getByRole("button", { name: "Visa alla (11)" }),
    ).toBeInTheDocument();
    expect(screen.queryByText("+6 fler")).toBeNull();
  });

  it("keeps the +N line when the card cannot open the list", () => {
    render(
      <WorkCard state="ready" labels={cardLabelsSv} frame={frame(5, 11)} />,
    );

    expect(screen.getByText("+6 fler")).toBeInTheDocument();
  });
});

function item(
  index: number,
  overrides: Partial<WorkItemRecord> = {},
): WorkItemRecord {
  return {
    kind: "task",
    id: `019f0000-0000-7000-8000-00000000000${index}`,
    title: `Uppgift ${index}`,
    status: "todo",
    due_at: null,
    version: 1,
    ...overrides,
  };
}

function frame(count: number, total = count): WorkCardFrame {
  return {
    kind: "card",
    items: Array.from({ length: count }, (_, index) => item(index + 1)),
    total,
    truncated: total > count,
  };
}

/** A frame of `count` Task records that all have `status` now. */
function statusFrame(
  status: string,
  count: number,
  total = count,
  overrides: Partial<WorkItemRecord> = {},
): WorkCardFrame {
  return {
    kind: "card",
    items: Array.from({ length: count }, (_, index) =>
      item(index + 1, { status, ...overrides }),
    ),
    total,
    truncated: total > count,
  };
}

/** Flattens a label catalogue to dotted key paths so the two locales can be compared exactly. */
function keyPaths(value: Record<string, unknown>, prefix = ""): string[] {
  return Object.entries(value).flatMap(([key, child]) => {
    const full = prefix ? `${prefix}.${key}` : key;
    return child && typeof child === "object"
      ? keyPaths(child as Record<string, unknown>, full)
      : [full];
  });
}

describe("work card labels", () => {
  it("expose identical key sets for Swedish and English", () => {
    expect(keyPaths(cardLabelsSv).sort()).toEqual(
      keyPaths(cardLabelsEn).sort(),
    );
  });

  it("contain no empty values", () => {
    for (const catalogue of [cardLabelsSv, cardLabelsEn]) {
      for (const key of keyPaths(catalogue)) {
        const value = key
          .split(".")
          .reduce<unknown>(
            (node, part) => (node as Record<string, unknown>)[part],
            catalogue,
          );
        expect(String(value).trim(), key).not.toBe("");
      }
    }
  });

  it("picks Swedish only for Swedish host locales", () => {
    expect(cardLabelsFor("sv-SE")).toBe(cardLabelsSv);
    expect(cardLabelsFor("en-US")).toBe(cardLabelsEn);
    expect(cardLabelsFor("")).toBe(cardLabelsEn);
  });
});

describe("WorkCard", () => {
  it("shows a skeleton with a status line while loading", () => {
    const { container } = render(
      <WorkCard state="loading" labels={cardLabelsEn} />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(cardLabelsEn.loading);
    expect(
      container.querySelectorAll(".work-compact-skeleton").length,
    ).toBeGreaterThan(0);
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("shows the empty text when the list has no records", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(0)}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByRole("status")).toHaveTextContent(cardLabelsEn.empty);
    expect(screen.queryByRole("list")).toBeNull();
  });

  it("shows at most five rows and counts the rest as +N", () => {
    render(<WorkCard state="ready" labels={cardLabelsEn} frame={frame(7)} />);

    const rows = screen.getAllByRole("listitem");
    expect(rows).toHaveLength(5);
    expect(screen.getByText("Uppgift 5")).toBeInTheDocument();
    expect(screen.queryByText("Uppgift 6")).toBeNull();
    expect(screen.getByText("+2 more")).toBeInTheDocument();
  });

  it("counts the server total, not only the rows it sent", () => {
    render(
      <WorkCard state="ready" labels={cardLabelsEn} frame={frame(3, 40)} />,
    );

    expect(screen.getAllByRole("listitem")).toHaveLength(3);
    expect(screen.getByText("+37 more")).toBeInTheDocument();
  });

  it("shows no +N when every record fits", () => {
    render(<WorkCard state="ready" labels={cardLabelsEn} frame={frame(5)} />);

    expect(screen.queryByText(/^\+\d+ /)).toBeNull();
  });

  it("says +N fler in Swedish with the Swedish label set («fler», not «till»)", () => {
    render(<WorkCard state="ready" labels={cardLabelsSv} frame={frame(7)} />);

    expect(screen.getByText("+2 fler")).toBeInTheDocument();
  });

  it("uses the project status set for project records", () => {
    const projectFrame: WorkCardFrame = {
      kind: "card",
      items: [item(1, { kind: "project", status: "paused" })],
      total: 1,
      truncated: false,
    };
    render(
      <WorkCard state="ready" labels={cardLabelsEn} frame={projectFrame} />,
    );

    expect(screen.getByText(cardLabelsEn.kind.project)).toBeInTheDocument();
    expect(
      screen.getByText(cardLabelsEn.projectStatus.paused),
    ).toBeInTheDocument();
  });

  it("shows an unknown status as it arrived", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={{
          kind: "card",
          items: [item(1, { status: "doing" })],
          total: 1,
          truncated: false,
        }}
      />,
    );

    expect(screen.getByText("doing")).toBeInTheDocument();
  });

  it("shows the error text and calls onRetry from Try again", async () => {
    const onRetry = vi.fn();
    render(
      <WorkCard
        state="error"
        labels={cardLabelsEn}
        appTitle="Work"
        locale="en-GB"
        subject="work"
        onRetry={onRetry}
      />,
    );

    expect(screen.getByText("Work")).toBeInTheDocument();
    expect(screen.getByRole("alert")).toHaveTextContent(
      "Couldn’t load your tasks",
    );
    await userEvent.click(
      screen.getByRole("button", { name: cardLabelsEn.retry }),
    );
    expect(onRetry).toHaveBeenCalledTimes(1);
  });

  it.each([
    ["en-GB", cardLabelsEn, "work:hierarchy", "Couldn’t load your projects"],
    ["en-GB", cardLabelsEn, "contacts", "Couldn’t load your contacts"],
    ["sv-SE", cardLabelsSv, "work:hierarchy", "Projekten kunde inte hämtas"],
    ["sv-SE", cardLabelsSv, "contacts", "Kontakterna kunde inte hämtas"],
  ])(
    "names what Try again reads in the heading (%s, %s)",
    (locale, labels, subject, heading) => {
      render(
        <WorkCard
          state="error"
          labels={labels}
          appTitle="Work"
          locale={locale}
          subject={subject}
          onRetry={vi.fn()}
        />,
      );

      expect(screen.getByRole("alert")).toHaveTextContent(heading);
    },
  );

  it("omits the retry button when no retry is given", () => {
    render(
      <WorkCard
        state="error"
        labels={cardLabelsEn}
        appTitle="Work"
        locale="en-GB"
        subject="work"
      />,
    );

    expect(screen.getByRole("alert")).toBeInTheDocument();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("calls onOpen from the Open action", async () => {
    const onOpen = vi.fn();
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(2)}
        onOpen={onOpen}
      />,
    );

    await userEvent.click(screen.getByRole("button", { name: "Show all (2)" }));
    expect(onOpen).toHaveBeenCalledTimes(1);
  });

  it("never shows more than two actions in any state", () => {
    const callbacks = { onOpen: vi.fn(), onRetry: vi.fn() };
    const states = [
      render(<WorkCard state="loading" labels={cardLabelsEn} />),
      render(
        <WorkCard
          state="error"
          labels={cardLabelsEn}
          appTitle="Work"
          locale="en-GB"
          subject="work"
          {...callbacks}
        />,
      ),
      render(
        <WorkCard
          state="ready"
          labels={cardLabelsEn}
          frame={frame(7)}
          onOpen={callbacks.onOpen}
        />,
      ),
    ];

    for (const view of states) {
      expect(
        view.container.querySelectorAll("button").length,
      ).toBeLessThanOrEqual(2);
      view.unmount();
    }
  });

  it("renders Swedish text with the Swedish label set", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={frame(1)}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText("1 uppgift, nu att göra")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: "Visa alla (1)" }),
    ).toBeInTheDocument();
    // Task rows do not repeat the kind word.
    expect(screen.queryByText(cardLabelsSv.kind.task)).toBeNull();
  });
});

describe("work card headline", () => {
  it("says where the tasks went when they all share one status (plural)", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("in_progress", 3)}
      />,
    );

    expect(screen.getByText("3 tasks, now in progress")).toBeInTheDocument();
    // The region is named by the title; the status sentence is a line under it.
    expect(screen.getByRole("region")).toHaveAccessibleName("Changes (3)");
  });

  it("uses the singular for one task", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("in_progress", 1)}
      />,
    );

    expect(screen.getByText("1 task, now in progress")).toBeInTheDocument();
  });

  it("says the Swedish plural and singular for Swedish cards", () => {
    const { unmount } = render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={statusFrame("in_progress", 3)}
      />,
    );
    expect(screen.getByText("3 uppgifter, nu pågår")).toBeInTheDocument();
    unmount();

    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={statusFrame("in_progress", 1)}
      />,
    );
    expect(screen.getByText("1 uppgift, nu pågår")).toBeInTheDocument();
  });

  it("counts the changes when the tasks have different statuses", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={{
          kind: "card",
          items: [
            item(1, { status: "todo" }),
            item(2, { status: "in_progress" }),
          ],
          total: 2,
          truncated: false,
        }}
      />,
    );

    // The title counts the changes; the status sentence is absent when the statuses differ.
    expect(screen.getByText("Changes (2)")).toBeInTheDocument();
    expect(screen.queryByText(/nu |now /)).toBeNull();
  });

  it("counts the changes, not the status, when the records are projects", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("active", 2, 2, { kind: "project" })}
      />,
    );

    expect(screen.getByText("Changes (2)")).toBeInTheDocument();
  });

  it("titles one project change with the count in English and Swedish, under the Work eyebrow", () => {
    const { unmount } = render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("active", 1, 1, { kind: "project" })}
      />,
    );
    expect(screen.getByText("Changes (1)")).toBeInTheDocument();
    expect(screen.getByText("Work")).toBeInTheDocument();
    unmount();

    render(
      <WorkCard
        state="ready"
        labels={cardLabelsSv}
        frame={statusFrame("active", 1, 1, { kind: "project" })}
      />,
    );
    expect(screen.getByText("Ändringar (1)")).toBeInTheDocument();
    expect(screen.getByText("Arbete")).toBeInTheDocument();
  });

  it("counts instead of naming a status when the card holds only part of the list", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("in_progress", 3, 40)}
      />,
    );

    expect(screen.getByText("Changes (40)")).toBeInTheDocument();
  });

  it("falls back to the plain title when there are no changes", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={frame(0)}
        onOpen={vi.fn()}
      />,
    );

    expect(screen.getByText(cardLabelsEn.title)).toBeInTheDocument();
  });
});

describe("work card rows", () => {
  it("shows the previous and new status when the record carries both", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={{
          kind: "card",
          items: [item(1, { status: "in_progress", previous_status: "todo" })],
          total: 1,
          truncated: false,
        }}
      />,
    );

    expect(screen.getByText("To do → In progress")).toBeInTheDocument();
  });

  it("shows only the new status when the previous one is missing", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={statusFrame("in_progress", 1)}
      />,
    );

    expect(
      screen.getByText("In progress", { selector: ".work-chip" }),
    ).toBeInTheDocument();
    expect(screen.queryByText(/→/)).toBeNull();
  });

  it("shows only the new status when previous and new are the same", () => {
    render(
      <WorkCard
        state="ready"
        labels={cardLabelsEn}
        frame={{
          kind: "card",
          items: [item(1, { status: "todo", previous_status: "todo" })],
          total: 1,
          truncated: false,
        }}
      />,
    );

    expect(screen.queryByText(/→/)).toBeNull();
  });
});
