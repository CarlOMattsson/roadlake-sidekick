import { act, fireEvent, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MoveAllUndo } from "@/features/work-app/agenda/parts/move-all-overdue";
import { UNDO_MS } from "@/features/mcp-apps/ui/undo-hold";
import { workEn } from "@/features/work-app/shared/labels";

/*
 * The Ångra line after "Flytta N till imorgon" counts down with the family's hold (undo-hold.ts): the same time,
 * paused while the pointer or focus is on it, and cancelled when it goes. Simulated host: this proves the line's
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

/** Ångra takes focus when focus was lost with the confirm button, and focus holds the time; let it go. */
function releaseFocus() {
  act(() => {
    button().blur();
  });
}

const button = () => screen.getByRole("button", { name: workEn.agendaUndo });
const line = () => button().parentElement!;

it("expires after the family's Undo time, not before", () => {
  const { onExpire } = renderLine();
  releaseFocus();
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
  releaseFocus();
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

it("stands still while focus is in it", () => {
  const { onExpire } = renderLine();
  fireEvent.focus(button());
  act(() => {
    vi.advanceTimersByTime(UNDO_MS * 2);
  });
  expect(onExpire).not.toHaveBeenCalled();
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
