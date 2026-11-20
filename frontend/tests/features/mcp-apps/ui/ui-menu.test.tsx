import { act, fireEvent, render, screen } from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";
import {
  Menu,
  MenuItem,
  menuButtonKeys,
  type MenuCloseReason,
} from "@/features/mcp-apps/ui/menu";

/** A ⋯ button and its menu, as the rooms use them: the caller owns `open`. */
function Harness({
  onChoose = () => undefined,
  onClosed = () => undefined,
}: {
  onChoose?: (label: string) => void;
  onClosed?: (reason: MenuCloseReason) => void;
}) {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  return (
    <>
      <button
        ref={button}
        type="button"
        aria-label="Fler val"
        aria-expanded={open}
        aria-controls="menu"
        onClick={() => setOpen(!open)}
        onKeyDown={menuButtonKeys(open, setOpen)}
      >
        ⋯
      </button>
      <p>Utanför</p>
      <Menu
        id="menu"
        open={open}
        anchor={button}
        onClose={(reason) => {
          onClosed(reason);
          setOpen(false);
        }}
      >
        {["Redigera", "Uppdatera", "Minne och kontroll"].map((label) => (
          <MenuItem
            key={label}
            label={label}
            onChoose={() => {
              onChoose(label);
              setOpen(false);
            }}
          />
        ))}
        <MenuItem label="Ta bort" danger onChoose={() => onChoose("Ta bort")} />
      </Menu>
    </>
  );
}

const menuOf = () => document.getElementById("menu")!;
const more = () => screen.getByRole("button", { name: "Fler val" });

afterEach(() => {
  delete document.documentElement.dataset.hostPointer;
});

describe("Menu as a popover (a fine pointer)", () => {
  function setup(props?: Parameters<typeof Harness>[0]) {
    document.documentElement.dataset.hostPointer = "fine";
    return render(<Harness {...props} />);
  }

  it("opens on a click with the focus on its first entry, and moves nothing on the page", () => {
    setup();
    const menu = menuOf();
    expect(menu).not.toBeVisible();
    fireEvent.click(more());
    expect(menu).toBeVisible();
    expect(menu).toHaveClass("sk-menu-popover");
    expect(menu).not.toHaveClass("sk-menu-panel");
    // jsdom has no Popover API, so this is the fixed box without the attribute (browsers: e2e menu-popover spec).
    expect(menu).not.toHaveAttribute("popover");
    expect(menu).toHaveAttribute("data-menu", "popover");
    expect(more()).toHaveAttribute("aria-expanded", "true");
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Redigera" }),
    );
  });

  it("moves the focus with ↓ and ↑ (wrapping), Home and End", () => {
    setup();
    fireEvent.click(more());
    const name = () => document.activeElement?.textContent;
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(name()).toBe("Uppdatera");
    fireEvent.keyDown(document.activeElement!, { key: "End" });
    expect(name()).toBe("Ta bort");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowDown" });
    expect(name()).toBe("Redigera");
    fireEvent.keyDown(document.activeElement!, { key: "ArrowUp" });
    expect(name()).toBe("Ta bort");
    fireEvent.keyDown(document.activeElement!, { key: "Home" });
    expect(name()).toBe("Redigera");
  });

  it("opens from the button's ↓ on the first entry and its ↑ on the last", () => {
    setup();
    fireEvent.keyDown(more(), { key: "ArrowDown" });
    expect(menuOf()).toBeVisible();
    expect(document.activeElement?.textContent).toBe("Redigera");
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    fireEvent.keyDown(more(), { key: "ArrowUp" });
    expect(document.activeElement?.textContent).toBe("Ta bort");
  });

  it("closes on one Escape, with the focus back on the button and the key stopped there", () => {
    const closed = vi.fn();
    const outer = vi.fn();
    setup({ onClosed: closed });
    window.addEventListener("keydown", outer);
    fireEvent.click(more());
    fireEvent.keyDown(document.activeElement!, { key: "Escape" });
    window.removeEventListener("keydown", outer);
    expect(menuOf()).not.toBeVisible();
    expect(closed).toHaveBeenCalledWith("escape");
    expect(document.activeElement).toBe(more());
    expect(outer).not.toHaveBeenCalled();
  });

  it("closes on Escape on the button itself", () => {
    setup();
    fireEvent.keyDown(more(), { key: "ArrowDown" });
    more().focus();
    fireEvent.keyDown(more(), { key: "Escape" });
    expect(menuOf()).not.toBeVisible();
  });

  it("closes on a press outside without a choice, and not on a press inside", () => {
    const chosen = vi.fn();
    const closed = vi.fn();
    setup({ onChoose: chosen, onClosed: closed });
    fireEvent.click(more());
    fireEvent.pointerDown(menuOf());
    expect(menuOf()).toBeVisible();
    act(() => {
      fireEvent.pointerDown(screen.getByText("Utanför"));
    });
    expect(menuOf()).not.toBeVisible();
    expect(closed).toHaveBeenCalledWith("outside");
    expect(chosen).not.toHaveBeenCalled();
  });

  it("is closed by its own button (a toggle), not by the press that reaches it", () => {
    const closed = vi.fn();
    setup({ onClosed: closed });
    fireEvent.click(more());
    fireEvent.pointerDown(more());
    expect(menuOf()).toBeVisible();
    fireEvent.click(more());
    expect(menuOf()).not.toBeVisible();
    expect(closed).not.toHaveBeenCalled();
  });

  it("closes on Tab and hands the focus to the button, so Tab moves on from there", () => {
    const closed = vi.fn();
    setup({ onClosed: closed });
    fireEvent.click(more());
    const tab = fireEvent.keyDown(document.activeElement!, { key: "Tab" });
    expect(tab).toBe(true);
    expect(closed).toHaveBeenCalledWith("tab");
    expect(menuOf()).not.toBeVisible();
    expect(document.activeElement).toBe(more());
  });

  it("chooses with Enter (a click on the entry) and draws a deletion as danger", () => {
    const chosen = vi.fn();
    setup({ onChoose: chosen });
    fireEvent.click(more());
    fireEvent.click(screen.getByRole("button", { name: "Uppdatera" }));
    expect(chosen).toHaveBeenCalledWith("Uppdatera");
    expect(menuOf()).not.toBeVisible();
    fireEvent.click(more());
    expect(screen.getByRole("button", { name: "Ta bort" })).toHaveClass(
      "sk-menu-item",
      "sk-menu-item--danger",
    );
  });
});

describe("Menu on a phone (a coarse pointer in a narrow frame)", () => {
  function setup() {
    document.documentElement.dataset.hostPointer = "coarse";
    return render(<Harness />);
  }

  it("is the family's panel in the flow, and a click leaves the focus on the button", () => {
    setup();
    fireEvent.click(more());
    const menu = menuOf();
    expect(menu).toBeVisible();
    expect(menu).toHaveClass("sk-menu-panel");
    expect(menu).not.toHaveAttribute("popover");
    expect(menu).toHaveAttribute("data-menu", "panel");
    expect(document.activeElement).not.toBe(
      screen.getByRole("button", { name: "Redigera" }),
    );
  });

  it("closes on Escape with the focus on the button, and stays open on a press outside", () => {
    setup();
    fireEvent.click(more());
    const first = screen.getByRole("button", { name: "Redigera" });
    first.focus();
    fireEvent.pointerDown(screen.getByText("Utanför"));
    expect(menuOf()).toBeVisible();
    fireEvent.keyDown(first, { key: "Escape" });
    expect(menuOf()).not.toBeVisible();
    expect(document.activeElement).toBe(more());
  });

  it("switches to the popover when the host reports a mouse", async () => {
    setup();
    fireEvent.click(more());
    expect(menuOf()).toHaveClass("sk-menu-panel");
    await act(async () => {
      document.documentElement.dataset.hostPointer = "fine";
      // The MutationObserver reports in a microtask.
      await Promise.resolve();
    });
    expect(menuOf()).toHaveClass("sk-menu-popover");
  });
});

describe("Menu as a context menu", () => {
  it("finds its anchor from the menu element and gives the focus back to it", () => {
    document.documentElement.dataset.hostPointer = "fine";
    function Row() {
      const [open, setOpen] = useState(true);
      return (
        <ul>
          <li>
            <button type="button">Boka plattsättare</button>
            {open && (
              <Menu
                anchor={(menu) =>
                  menu.closest("li")?.querySelector("button") ?? null
                }
                align="start"
                point={{ x: 40, y: 60 }}
                onClose={() => setOpen(false)}
              >
                <MenuItem label="Pågår" onChoose={() => undefined} />
              </Menu>
            )}
          </li>
        </ul>
      );
    }
    render(<Row />);
    const choice = screen.getByRole("button", { name: "Pågår" });
    expect(document.activeElement).toBe(choice);
    expect(choice.closest("[data-menu]")).toHaveAttribute(
      "data-align",
      "point",
    );
    fireEvent.keyDown(choice, { key: "Escape" });
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Boka plattsättare" }),
    );
  });
});
