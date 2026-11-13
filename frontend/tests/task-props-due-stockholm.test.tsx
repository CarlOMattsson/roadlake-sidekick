import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import { workEn } from "@/features/work-app/shared/labels";
import { TaskProps } from "@/features/work-app/tasks/task-detail-controls";

// The Task detail's due choices give 23:59 on the Stockholm calendar day, whatever the browser's zone.
describe("TaskProps due choices in Stockholm time", () => {
  const original = process.env.TZ;
  beforeEach(() => {
    process.env.TZ = "America/New_York";
    // Monday 00:30 in Stockholm (CET) is still Sunday 18:30 in New York.
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-08T23:30:00Z"));
  });
  afterEach(() => {
    vi.useRealTimers();
    if (original === undefined) delete process.env.TZ;
    else process.env.TZ = original;
  });

  function open(onDue: (dueAt: string) => void) {
    render(
      <TaskProps
        hasDue={false}
        busy={false}
        status="todo"
        labels={workEn}
        onDue={onDue}
        onStatus={vi.fn()}
      />,
    );
    fireEvent.click(screen.getByRole("button", { name: workEn.addDue }));
  }

  it("Today, Tomorrow and Next week are 23:59 on the Stockholm days 9, 10 and 16 November", () => {
    const onDue = vi.fn();
    open(onDue);
    fireEvent.click(screen.getByRole("button", { name: workEn.dueToday }));
    expect(onDue).toHaveBeenLastCalledWith("2026-11-09T22:59:00.000Z");
    fireEvent.click(screen.getByRole("button", { name: workEn.addDue }));
    fireEvent.click(screen.getByRole("button", { name: /Tomorrow/ }));
    expect(onDue).toHaveBeenLastCalledWith("2026-11-10T22:59:00.000Z");
    fireEvent.click(screen.getByRole("button", { name: workEn.addDue }));
    fireEvent.click(screen.getByRole("button", { name: workEn.dueNextWeek }));
    expect(onDue).toHaveBeenLastCalledWith("2026-11-16T22:59:00.000Z");
  });

  it("a picked day is 23:59 Stockholm on that day, summer and winter time", () => {
    const onDue = vi.fn();
    open(onDue);
    fireEvent.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    const input = screen.getByLabelText(workEn.rescheduleDate);
    fireEvent.input(input, { target: { value: "2026-03-29" } });
    expect(onDue).toHaveBeenLastCalledWith("2026-03-29T21:59:00.000Z");
    fireEvent.click(screen.getByRole("button", { name: workEn.addDue }));
    fireEvent.click(
      screen.getByRole("button", { name: workEn.rescheduleDate }),
    );
    fireEvent.input(screen.getByLabelText(workEn.rescheduleDate), {
      target: { value: "2026-10-25" },
    });
    expect(onDue).toHaveBeenLastCalledWith("2026-10-25T22:59:00.000Z");
  });
});
