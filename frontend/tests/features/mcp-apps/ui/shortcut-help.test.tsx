import { act, fireEvent, render, screen, within } from "@testing-library/react";
import { useState } from "react";
import { describe, expect, it, vi } from "vitest";

import { ShortcutHelp } from "@/features/mcp-apps/ui/shortcut-help";
import type { ShortcutHelpGroup } from "@/features/mcp-apps/ui/shortcut-registry";

const groups: ShortcutHelpGroup[] = [
  {
    id: "global",
    title: "Everywhere",
    entries: [
      { keys: ["?"], label: "Show shortcuts" },
      { keys: ["g 1"], label: "Go to Agenda" },
    ],
  },
  {
    id: "agenda",
    title: "Agenda",
    entries: [
      { keys: ["j", "ArrowDown"], label: "Next row" },
      { keys: ["Mod+Enter"], label: "Save" },
    ],
  },
];

function Harness({ onChar }: { onChar?: (on: boolean) => void }) {
  const [open, setOpen] = useState(false);
  return (
    <>
      <button type="button" onClick={() => setOpen(true)}>
        Help
      </button>
      <ShortcutHelp
        open={open}
        onClose={() => setOpen(false)}
        title="Keyboard shortcuts"
        closeLabel="Close"
        groups={groups}
        charKeys={
          onChar
            ? { label: "Single-key shortcuts", on: true, onChange: onChar }
            : undefined
        }
      />
    </>
  );
}

function openSheet() {
  const opener = screen.getByRole("button", { name: "Help" });
  opener.focus();
  fireEvent.click(opener);
  return opener;
}

describe("ShortcutHelp", () => {
  it("renders the groups with one keycap per key part", () => {
    render(<Harness />);
    openSheet();

    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(
      within(dialog).getByRole("heading", { name: "Everywhere" }),
    ).toBeTruthy();
    expect(
      within(dialog).getByRole("heading", { name: "Agenda" }),
    ).toBeTruthy();

    const row = within(dialog).getByText("Go to Agenda").closest("div");
    expect(
      [...(row?.querySelectorAll("kbd") ?? [])].map((k) => k.textContent),
    ).toEqual(["g", "1"]);
    const next = within(dialog).getByText("Next row").closest("div");
    expect(
      [...(next?.querySelectorAll("kbd") ?? [])].map((k) => k.textContent),
    ).toEqual(["j", "↓"]);
  });

  it("moves focus to the close button on opening", () => {
    render(<Harness />);
    openSheet();

    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Close" }),
    );
  });

  it("closes on Esc, takes the key, and returns focus to the opener", () => {
    const onWindowKey = vi.fn();
    window.addEventListener("keydown", onWindowKey);
    render(<Harness />);
    const opener = openSheet();
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });

    const escape = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      dialog.querySelector("button")?.dispatchEvent(escape);
    });

    window.removeEventListener("keydown", onWindowKey);
    expect(escape.defaultPrevented).toBe(true);
    expect(onWindowKey).not.toHaveBeenCalled();
    expect(dialog.hasAttribute("open")).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("closes on the native cancel event", () => {
    render(<Harness />);
    const opener = openSheet();
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });

    fireEvent(dialog, new Event("cancel", { cancelable: true }));

    expect(dialog.hasAttribute("open")).toBe(false);
    expect(document.activeElement).toBe(opener);
  });

  it("closes with the × and with a click on the backdrop", () => {
    render(<Harness />);
    const opener = openSheet();
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });

    fireEvent.click(screen.getByRole("button", { name: "Close" }));
    expect(dialog.hasAttribute("open")).toBe(false);
    expect(document.activeElement).toBe(opener);

    fireEvent.click(opener);
    expect(dialog.hasAttribute("open")).toBe(true);
    fireEvent.click(within(dialog).getByText("Save"));
    expect(dialog.hasAttribute("open")).toBe(true);
    fireEvent.click(dialog);
    expect(dialog.hasAttribute("open")).toBe(false);
  });

  it("calls onChange from the single-key switch", () => {
    const onChar = vi.fn();
    render(<Harness onChar={onChar} />);
    openSheet();

    fireEvent.click(
      screen.getByRole("switch", { name: "Single-key shortcuts" }),
    );

    expect(onChar).toHaveBeenCalledWith(false);
  });
});
