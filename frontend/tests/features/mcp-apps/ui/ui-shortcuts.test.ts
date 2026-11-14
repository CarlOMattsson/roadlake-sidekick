import { renderHook } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  SEQUENCE_TIMEOUT_MS,
  useShortcuts,
  type ShortcutMap,
} from "@/features/mcp-apps/ui/shortcuts";

/* Simulated key presses: a real KeyboardEvent dispatched into the DOM, as a browser would. */
function press(
  key: string,
  init: KeyboardEventInit = {},
  target: EventTarget = window,
): KeyboardEvent {
  const event = new KeyboardEvent("keydown", {
    key,
    bubbles: true,
    cancelable: true,
    ...init,
  });
  target.dispatchEvent(event);
  return event;
}

function mount(map: ShortcutMap, enabled = true) {
  return renderHook(
    (props: { map: ShortcutMap; enabled: boolean }) =>
      useShortcuts(props.map, { enabled: props.enabled }),
    { initialProps: { map, enabled } },
  );
}

describe("useShortcuts single keys", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("fires a plain key once and cancels its default action", () => {
    const j = vi.fn();
    mount({ j });

    const event = press("j");

    expect(j).toHaveBeenCalledTimes(1);
    expect(event.defaultPrevented).toBe(true);
  });

  it("fires named keys such as arrows and Enter", () => {
    const down = vi.fn();
    const enter = vi.fn();
    mount({ ArrowDown: down, Enter: enter });

    press("ArrowDown");
    press("Enter");

    expect(down).toHaveBeenCalledTimes(1);
    expect(enter).toHaveBeenCalledTimes(1);
  });

  it("does not fire a plain key when Ctrl, Alt or Meta is held", () => {
    const j = vi.fn();
    mount({ j });

    press("j", { ctrlKey: true });
    press("j", { altKey: true });
    press("j", { metaKey: true });

    expect(j).not.toHaveBeenCalled();
  });

  it("fires a combo only when its modifier is held and nothing else is", () => {
    const save = vi.fn();
    const shiftDown = vi.fn();
    mount({ "Ctrl+Enter": save, "Shift+ArrowDown": shiftDown });

    press("Enter");
    press("Enter", { ctrlKey: true });
    press("ArrowDown");
    press("ArrowDown", { shiftKey: true });

    expect(save).toHaveBeenCalledTimes(1);
    expect(shiftDown).toHaveBeenCalledTimes(1);
  });

  it("treats Mod as Ctrl or Cmd", () => {
    const save = vi.fn();
    mount({ "Mod+Enter": save });

    press("Enter", { ctrlKey: true });
    press("Enter", { metaKey: true });

    expect(save).toHaveBeenCalledTimes(2);
  });

  it("fires a printable character whose shift is implied by the key, such as ?", () => {
    const help = vi.fn();
    mount({ "?": help });

    press("?", { shiftKey: true });

    expect(help).toHaveBeenCalledTimes(1);
  });
});

describe("useShortcuts sequences", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("fires g a when both keys arrive within one second", () => {
    const agenda = vi.fn();
    mount({ "g a": agenda });

    press("g");
    vi.advanceTimersByTime(SEQUENCE_TIMEOUT_MS - 1);
    press("a");

    expect(agenda).toHaveBeenCalledTimes(1);
  });

  it("drops the sequence when the second key arrives after one second", () => {
    const agenda = vi.fn();
    mount({ "g a": agenda });

    press("g");
    vi.advanceTimersByTime(SEQUENCE_TIMEOUT_MS + 1);
    press("a");

    expect(agenda).not.toHaveBeenCalled();
  });

  it("drops the sequence when an unrelated key comes in between", () => {
    const agenda = vi.fn();
    mount({ "g a": agenda });

    press("g");
    press("x");
    press("a");

    expect(agenda).not.toHaveBeenCalled();
  });

  it("runs a single-key shortcut that arrives during a pending sequence and drops the sequence", () => {
    const next = vi.fn();
    const agenda = vi.fn();
    mount({ "g a": agenda, j: next });

    press("g");
    press("j");
    press("a");

    expect(next).toHaveBeenCalledTimes(1);
    expect(agenda).not.toHaveBeenCalled();
  });

  it("restarts a sequence when its first key is pressed again", () => {
    const agenda = vi.fn();
    mount({ "g a": agenda });

    press("g");
    press("g");
    press("a");

    expect(agenda).toHaveBeenCalledTimes(1);
  });
});

describe("useShortcuts fields and composition", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
    document.body.innerHTML = "";
  });

  it("ignores keys typed into input, textarea, select and contenteditable", () => {
    const j = vi.fn();
    mount({ j });

    const input = document.createElement("input");
    const textarea = document.createElement("textarea");
    const select = document.createElement("select");
    const editable = document.createElement("div");
    editable.setAttribute("contenteditable", "true");
    document.body.append(input, textarea, select, editable);

    for (const field of [input, textarea, select, editable]) {
      press("j", {}, field);
    }

    expect(j).not.toHaveBeenCalled();
  });

  it("does not start a sequence from inside a field", () => {
    const agenda = vi.fn();
    mount({ "g a": agenda });

    const input = document.createElement("input");
    document.body.append(input);
    press("g", {}, input);
    press("a");

    expect(agenda).not.toHaveBeenCalled();
  });

  it("ignores keys during IME composition", () => {
    const j = vi.fn();
    mount({ j });

    press("j", { isComposing: true });

    expect(j).not.toHaveBeenCalled();
  });
});

describe("useShortcuts lifecycle", () => {
  afterEach(() => {
    vi.useRealTimers();
  });

  it("attaches no listener while disabled, as in inline views", () => {
    const j = vi.fn();
    mount({ j }, false);

    const event = press("j");

    expect(j).not.toHaveBeenCalled();
    expect(event.defaultPrevented).toBe(false);
  });

  it("starts firing when enabled and stops again when unmounted", () => {
    const j = vi.fn();
    const { rerender, unmount } = mount({ j }, false);

    rerender({ map: { j }, enabled: true });
    press("j");
    expect(j).toHaveBeenCalledTimes(1);

    unmount();
    press("j");
    expect(j).toHaveBeenCalledTimes(1);
  });

  it("uses the latest action from a new map without re-binding", () => {
    const first = vi.fn();
    const second = vi.fn();
    const { rerender } = mount({ j: first });

    rerender({ map: { j: second }, enabled: true });
    press("j");

    expect(first).not.toHaveBeenCalled();
    expect(second).toHaveBeenCalledTimes(1);
  });
});
