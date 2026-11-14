import { createRef } from "react";
import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";

import { KeyScope, onEscapeKey } from "@/features/mcp-apps/ui/key-scope";

describe("KeyScope Escape", () => {
  it("runs onEscape for Escape from a control inside and keeps the key from bubbling", async () => {
    const user = userEvent.setup();
    const onEscape = vi.fn();
    const outer = vi.fn();
    render(
      <div onKeyDown={outer}>
        <KeyScope onEscape={onEscape}>
          <button type="button">Inside</button>
        </KeyScope>
      </div>,
    );
    screen.getByRole("button", { name: "Inside" }).focus();
    await user.keyboard("{Escape}");
    expect(onEscape).toHaveBeenCalledTimes(1);
    expect(outer).not.toHaveBeenCalled();
  });

  it("marks a handled Escape as default-prevented so window shortcuts skip it", () => {
    render(
      <KeyScope onEscape={() => undefined}>
        <button type="button">Inside</button>
      </KeyScope>,
    );
    const notPrevented = fireEvent.keyDown(
      screen.getByRole("button", { name: "Inside" }),
      { key: "Escape" },
    );
    expect(notPrevented).toBe(false);
  });

  it("lets Escape through when no onEscape is set", async () => {
    const user = userEvent.setup();
    const outer = vi.fn();
    render(
      <div onKeyDown={outer}>
        <KeyScope>
          <button type="button">Inside</button>
        </KeyScope>
      </div>,
    );
    screen.getByRole("button", { name: "Inside" }).focus();
    await user.keyboard("{Escape}");
    expect(outer).toHaveBeenCalledTimes(1);
  });

  it("ignores other keys", async () => {
    const user = userEvent.setup();
    const onEscape = vi.fn();
    render(
      <KeyScope onEscape={onEscape}>
        <button type="button">Inside</button>
      </KeyScope>,
    );
    screen.getByRole("button", { name: "Inside" }).focus();
    await user.keyboard("{Enter}a{ArrowDown}");
    expect(onEscape).not.toHaveBeenCalled();
  });

  it("leaves an Escape that a control inside already handled", () => {
    const onEscape = vi.fn();
    render(
      <KeyScope onEscape={onEscape}>
        <input
          aria-label="Field"
          onKeyDown={(event) => event.preventDefault()}
        />
      </KeyScope>,
    );
    fireEvent.keyDown(screen.getByLabelText("Field"), { key: "Escape" });
    expect(onEscape).not.toHaveBeenCalled();
  });

  it("leaves an Escape that confirms an IME composition", () => {
    const onEscape = vi.fn();
    render(
      <KeyScope onEscape={onEscape}>
        <input aria-label="Field" />
      </KeyScope>,
    );
    fireEvent.keyDown(screen.getByLabelText("Field"), {
      key: "Escape",
      isComposing: true,
    });
    expect(onEscape).not.toHaveBeenCalled();
  });
});

describe("KeyScope roving focus", () => {
  it("moves focus between the buttons with the arrow keys, Home and End", async () => {
    const user = userEvent.setup();
    render(
      <KeyScope roving role="group" aria-label="Views">
        <button type="button">One</button>
        <button type="button">Two</button>
        <button type="button">Three</button>
      </KeyScope>,
    );
    const one = screen.getByRole("button", { name: "One" });
    const two = screen.getByRole("button", { name: "Two" });
    const three = screen.getByRole("button", { name: "Three" });
    one.focus();
    await user.keyboard("{ArrowRight}");
    expect(two).toHaveFocus();
    await user.keyboard("{End}");
    expect(three).toHaveFocus();
    await user.keyboard("{ArrowRight}");
    expect(one).toHaveFocus();
    await user.keyboard("{Home}");
    expect(one).toHaveFocus();
  });

  it("does not move focus when roving is off", async () => {
    const user = userEvent.setup();
    render(
      <KeyScope>
        <button type="button">One</button>
        <button type="button">Two</button>
      </KeyScope>,
    );
    const one = screen.getByRole("button", { name: "One" });
    one.focus();
    await user.keyboard("{ArrowRight}");
    expect(one).toHaveFocus();
  });
});

describe("KeyScope element", () => {
  it("renders a div by default and passes role, label and ref through", () => {
    const ref = createRef<HTMLDivElement>();
    render(
      <KeyScope ref={ref} role="group" aria-label="Panel" className="panel">
        <button type="button">Inside</button>
      </KeyScope>,
    );
    const group = screen.getByRole("group", { name: "Panel" });
    expect(group.tagName).toBe("DIV");
    expect(group).toHaveClass("panel");
    expect(ref.current).toBe(group);
  });

  it("renders a real form when asked, so validity checks and FormData still work", () => {
    const ref = createRef<HTMLFormElement>();
    render(
      <KeyScope as="form" ref={ref} aria-label="Edit">
        <input name="name" defaultValue="Milk" required />
      </KeyScope>,
    );
    expect(ref.current?.tagName).toBe("FORM");
    expect(new FormData(ref.current!).get("name")).toBe("Milk");
  });

  it("calls a caller onKeyDown for keys the scope does not handle itself", async () => {
    const user = userEvent.setup();
    const onKeyDown = vi.fn();
    render(
      <KeyScope onKeyDown={onKeyDown}>
        <button type="button">Inside</button>
      </KeyScope>,
    );
    screen.getByRole("button", { name: "Inside" }).focus();
    await user.keyboard("{Tab}");
    expect(onKeyDown).toHaveBeenCalled();
  });
});

describe("onEscapeKey", () => {
  it("runs the action on a toggle button's Escape and only then", async () => {
    const user = userEvent.setup();
    const action = vi.fn();
    render(
      <button type="button" onKeyDown={(event) => onEscapeKey(event, action)}>
        Toggle
      </button>,
    );
    screen.getByRole("button", { name: "Toggle" }).focus();
    await user.keyboard("x");
    expect(action).not.toHaveBeenCalled();
    await user.keyboard("{Escape}");
    expect(action).toHaveBeenCalledTimes(1);
  });
});
