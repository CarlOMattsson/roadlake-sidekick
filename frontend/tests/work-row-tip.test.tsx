import { fireEvent, render, screen } from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  RowMenuTip,
  rowMenuHandlers,
} from "@/features/work-app/shared/row-menu";
import { workEn, workSv } from "@/features/work-app/shared/labels";

// The long-press tip (designsystem §3 "Listrad"): last in Agenda and Status until the quick choices are first
// opened, then gone for good (the frame's storage when it may be used, the document for the session when not).

function List({ labels = workSv }: { labels?: typeof workSv }) {
  const [open, setOpen] = useState(false);
  return (
    <div>
      <ul>
        <li {...rowMenuHandlers(open, setOpen)}>
          <button type="button">Betala hyran</button>
        </li>
      </ul>
      <RowMenuTip labels={labels} />
    </div>
  );
}

afterEach(() => {
  vi.restoreAllMocks();
  delete document.documentElement.dataset.rowMenu;
  localStorage.clear();
});

it("shows the tip in Swedish and English until the first long press", () => {
  const { unmount } = render(<List />);
  expect(
    screen.getByText("Håll inne en uppgift för fler val."),
  ).toBeInTheDocument();
  unmount();
  render(<List labels={workEn} />);
  expect(
    screen.getByText("Touch and hold a task for more options."),
  ).toBeInTheDocument();
});

it("leaves after the first contextmenu and does not come back after a remount, since the storage keeps it", () => {
  const { unmount } = render(<List />);
  fireEvent.contextMenu(screen.getByRole("listitem"));
  expect(screen.queryByText(workSv.rowMenuHint)).toBeNull();
  expect(localStorage.getItem("sidekick.rowMenuUsed")).toBe("1");
  unmount();
  delete document.documentElement.dataset.rowMenu;
  render(<List />);
  expect(screen.queryByText(workSv.rowMenuHint)).toBeNull();
});

it("leaves after Shift+F10 on a row as well", () => {
  render(<List />);
  fireEvent.keyDown(screen.getByRole("button"), {
    key: "F10",
    shiftKey: true,
  });
  expect(screen.queryByText(workSv.rowMenuHint)).toBeNull();
});

it("stays gone for the session when the frame may not use storage", () => {
  vi.spyOn(window, "localStorage", "get").mockImplementation(() => {
    throw new Error("no storage");
  });
  const { unmount } = render(<List />);
  fireEvent.contextMenu(screen.getByRole("listitem"));
  unmount();
  render(<List />);
  expect(screen.queryByText(workSv.rowMenuHint)).toBeNull();
});

// A long press does nothing with a mouse, so a fine pointer gets the right click and Shift+F10.
it("names the right click and Shift+F10 with a fine pointer, in Swedish and English", () => {
  vi.stubGlobal(
    "matchMedia",
    vi.fn((query: string) => ({ matches: query === "(pointer: fine)" })),
  );
  try {
    const { unmount } = render(<List />);
    expect(
      screen.getByText(
        "Högerklicka på en uppgift eller tryck Shift+F10 för fler val.",
      ),
    ).toBeInTheDocument();
    unmount();
    render(<List labels={workEn} />);
    expect(
      screen.getByText(
        "Right-click a task or press Shift+F10 for more options.",
      ),
    ).toBeInTheDocument();
  } finally {
    vi.unstubAllGlobals();
  }
});
