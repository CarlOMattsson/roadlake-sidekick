import { render, screen, within } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  taskPlaceLabelsEn,
  taskPlaceLabelsSv,
} from "@/features/work-app/tasks/task-place-labels";
import { TaskRepeat } from "@/features/work-app/tasks/task-repeat";

/* The repeat details under the repeat row (a simulated render of the component, not a real host): the weekday question,
   seven weekday buttons, the hint without a day, and the line with the next occurrence. */

const weekly = {
  frequency: "weekly" as const,
  interval: 1,
  weekdays: [4],
  day_of_month: null,
  last_weekday: false,
  until: null,
};

describe("the repeat details of a Task", () => {
  beforeEach(() => {
    vi.useFakeTimers({ toFake: ["Date"] });
    // Friday 20 November 2026, 10:00 in Stockholm.
    vi.setSystemTime(new Date("2026-11-20T09:00:00Z"));
  });
  afterEach(() => vi.useRealTimers());

  function show(
    rule: Parameters<typeof TaskRepeat>[0]["rule"],
    words = taskPlaceLabelsSv,
    dueAt: string | null = null,
  ) {
    return render(
      <TaskRepeat
        rule={rule}
        title="Måla taket"
        words={words}
        writable
        busy={false}
        dueAt={dueAt}
        onChoose={() => undefined}
      />,
    );
  }

  it("asks which days, shows seven weekday buttons and the next occurrence for a weekly rule", () => {
    show({ ...weekly, weekdays: [1] });
    expect(screen.getByText("Vilka dagar?")).toBeVisible();
    const days = within(
      screen.getByRole("group", { name: "Veckodagar för Måla taket" }),
    );
    expect(days.getAllByRole("button")).toHaveLength(7);
    expect(days.getByRole("button", { name: "tisdag" })).toHaveAttribute(
      "aria-pressed",
      "true",
    );
    expect(screen.getByText("Nästa gång: tis 24 nov")).toBeVisible();
    expect(screen.queryByText(/Utan vald dag/)).toBeNull();
  });

  it("says what happens without a chosen day, in Swedish and English", () => {
    const { unmount } = show({ ...weekly, weekdays: [] });
    expect(
      screen.getByText(
        "Utan vald dag: en vecka efter att uppgiften bockats av.",
      ),
    ).toBeVisible();
    expect(screen.getByText("Nästa gång: fre 27 nov")).toBeVisible();
    unmount();

    show({ ...weekly, interval: 2, weekdays: [] }, taskPlaceLabelsEn);
    expect(screen.getByText("Which days?")).toBeVisible();
    expect(
      screen.getByText("No day chosen: two weeks after the task is completed."),
    ).toBeVisible();
    expect(screen.getByText("Next: Fri 4 Dec")).toBeVisible();
  });

  it("shows the next occurrence of a monthly rule from the due date, and no weekday question", () => {
    show(
      { ...weekly, frequency: "monthly", weekdays: [] },
      taskPlaceLabelsSv,
      "2026-11-15T22:59:00Z",
    );
    expect(screen.queryByText("Vilka dagar?")).toBeNull();
    expect(screen.getByText("Nästa gång: tis 15 dec")).toBeVisible();
  });

  it("shows nothing for a Task that does not repeat", () => {
    show(null);
    expect(screen.queryByText(/Nästa gång/)).toBeNull();
    expect(screen.queryByText("Vilka dagar?")).toBeNull();
  });
});
