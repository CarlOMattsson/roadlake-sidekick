import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MoveAllUndo } from "@/features/work-app/agenda/parts/move-all-overdue";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn } from "@/features/work-app/shared/labels";

/*
 * The Ångra line after "Flytta N till imorgon" counts down with the family's hold (undo-hold.ts): the same time,
 * paused while the pointer is on it (not focus: Ångra takes focus itself), and cancelled when it goes. Simulated host: this proves the line's
 * wiring, not a real Claude or Android host.
 */

beforeEach(() => {
  vi.useFakeTimers();
});
afterEach(() => {
  vi.useRealTimers();
});

function renderLine(onExpire = vi.fn()) {
  const view = render(
    <MoveAllUndo
      labels={workEn}
      count={3}
      disabled={false}
      onUndo={vi.fn()}
      onExpire={onExpire}
    />,
  );
  return { onExpire, ...view };
}

const button = () => screen.getByRole("button", { name: workEn.agendaUndo });
const line = () => button().parentElement!;

it("expires after the family's Undo time, not before", () => {
  const { onExpire } = renderLine();
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 1);
  });
  expect(onExpire).not.toHaveBeenCalled();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(onExpire).toHaveBeenCalledTimes(1);
});

it("stands still while the pointer is over it and runs on with the time left", () => {
  const { onExpire } = renderLine();
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 4000);
  });
  fireEvent.pointerEnter(line());
  expect(line()).toHaveAttribute("data-held");
  act(() => {
    vi.advanceTimersByTime(UNDO_MS * 3);
  });
  expect(onExpire).not.toHaveBeenCalled();
  fireEvent.pointerLeave(line());
  expect(line()).not.toHaveAttribute("data-held");
  act(() => {
    vi.advanceTimersByTime(3999);
  });
  expect(onExpire).not.toHaveBeenCalled();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(onExpire).toHaveBeenCalledTimes(1);
});

it("runs out although Ångra has focus, and focus then goes to the group's button", () => {
  const onExpire = vi.fn();
  render(
    <article>
      <h2 tabIndex={-1}>{workEn.agenda}</h2>
      <button type="button" className="work-agenda-move-all">
        {workEn.moveAllOverdue(2)}
      </button>
      <MoveAllUndo
        labels={workEn}
        count={3}
        disabled={false}
        onUndo={vi.fn()}
        onExpire={onExpire}
      />
    </article>,
  );
  // The line puts focus on Ångra itself, and a tap with the finger moves it there too.
  expect(button()).toHaveFocus();
  fireEvent.focus(button());
  act(() => {
    vi.advanceTimersByTime(UNDO_MS - 1);
  });
  expect(onExpire).not.toHaveBeenCalled();
  act(() => {
    vi.advanceTimersByTime(1);
  });
  expect(onExpire).toHaveBeenCalledTimes(1);
  expect(
    screen.getByRole("button", { name: workEn.moveAllOverdue(2) }),
  ).toHaveFocus();
});

it("never expires once it has been unmounted", () => {
  const { onExpire, unmount } = renderLine();
  unmount();
  act(() => {
    vi.advanceTimersByTime(UNDO_MS * 2);
  });
  expect(onExpire).not.toHaveBeenCalled();
});

it("shows the family's time line under Ångra", () => {
  renderLine();
  expect(button()).toHaveClass("sk-undo-time");
});
