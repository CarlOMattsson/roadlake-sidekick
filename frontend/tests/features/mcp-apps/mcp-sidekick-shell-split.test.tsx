import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS } from "@/features/mcp-apps/router";
import { useUnsavedGuard } from "@/features/mcp-apps/unsaved-guard";
import { useRecordRow } from "@/features/mcp-apps/ui/split-layout";
import { useRoomShortcuts } from "@/features/mcp-apps/ui/shortcut-registry";

// The shell's split pane in a wide frame (desktop spec 2.1) with stub rooms: a list of three Tasks and a Task
// view with a field that holds unsaved edits. jsdom has no layout: the frame's width is stubbed, as in
// sidekick-shell-head.test.tsx.

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

function Row({ id, open }: { id: string; open: () => void }) {
  const record = useRecordRow({ room: "work", view: "task", id });
  return (
    <li data-sk-row="" {...record}>
      <button type="button" data-sk-open="" onClick={open}>
        {`Task ${id}`}
      </button>
    </li>
  );
}

function TaskView({ id }: { id: string }) {
  const [text, setText] = useState("");
  useUnsavedGuard(text !== "");
  return (
    <section>
      <h2>{`Title ${id}`}</h2>
      <label>
        Note
        <input value={text} onChange={(event) => setText(event.target.value)} />
      </label>
    </section>
  );
}

function ListView({ navigate }: ShellRoomProps) {
  useRoomShortcuts(
    { j: () => {} },
    { id: "rows", title: "Arbete", labels: { j: "Next" } },
  );
  return (
    <section>
      <h2>Agenda</h2>
      <ul>
        {["t1", "t2", "t3"].map((id) => (
          <Row
            key={id}
            id={id}
            open={() =>
              navigate?.({
                room: "work",
                view: "task",
                id,
                label: `Task ${id}`,
              })
            }
          />
        ))}
      </ul>
    </section>
  );
}

function Stub(props: ShellRoomProps) {
  if (props.entry.view === "task" && props.entry.id)
    return <TaskView id={props.entry.id} />;
  return <ListView {...props} />;
}

const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;

const start: NavEntry = { room: "work", view: "agenda" };

const realClientWidth = Object.getOwnPropertyDescriptor(
  HTMLElement.prototype,
  "clientWidth",
);
function stubFrameWidth(width: number) {
  Object.defineProperty(HTMLElement.prototype, "clientWidth", {
    configurable: true,
    get(this: HTMLElement) {
      return this.classList.contains("sk-frame") ? width : 0;
    },
  });
}

function setup(width: number) {
  stubFrameWidth(width);
  const onModelContext = vi.fn();
  render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
      onModelContext={onModelContext}
      onSendMessage={vi.fn().mockResolvedValue(true)}
    />,
  );
  return { onModelContext };
}

const panes = () =>
  Array.from(
    document.querySelectorAll<HTMLElement>(
      "[data-room='work'] .sk-rooms__layer:not([hidden])",
    ),
  );
const openTask = (id: string) =>
  fireEvent.click(screen.getByRole("button", { name: `Task ${id}` }));
const row = (id: string) =>
  document.querySelector<HTMLElement>(`[data-sk-record="work:task:${id}"]`);

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  if (realClientWidth)
    Object.defineProperty(
      HTMLElement.prototype,
      "clientWidth",
      realClientWidth,
    );
});

describe("the split pane in a wide frame", () => {
  it("shows the hints beside a list with nothing open, naming only the keys that are bound", () => {
    setup(1440);
    expect(document.querySelector(".sk-split")).toHaveAttribute(
      "data-split",
      "aside",
    );
    const aside = screen.getByRole("complementary", {
      name: "Välj en uppgift för att se den här",
    });
    expect(aside).toHaveTextContent("Välj rad");
    // The stub binds j but no n: N is not offered.
    expect(aside).not.toHaveTextContent("Ny");
  });

  it("opens a record beside the list, swaps it for the next without a stack, and tells the model once per record", () => {
    const { onModelContext } = setup(1440);
    openTask("t1");
    expect(document.querySelector(".sk-split")).toHaveAttribute(
      "data-split",
      "split",
    );
    const [list, detail] = panes();
    expect(list).toHaveAttribute("data-pane", "list");
    expect(detail).toHaveAttribute("data-pane", "detail");
    expect(screen.getByRole("heading", { name: "Title t1" })).toBeVisible();
    expect(row("t1")).toHaveAttribute("aria-current", "true");
    // The detail's head: the kind and the ×, and no Back row in the bar.
    expect(
      screen.getByRole("button", { name: "Stäng uppgiften" }),
    ).toHaveAttribute("aria-keyshortcuts", "Escape");
    expect(document.querySelector(".sk-rooms__bar .sk-back-header")).toBeNull();

    openTask("t2");
    expect(panes()).toHaveLength(2);
    expect(screen.getByRole("heading", { name: "Title t2" })).toBeVisible();
    expect(screen.queryByRole("heading", { name: "Title t1" })).toBeNull();
    expect(row("t2")).toHaveAttribute("aria-current", "true");
    expect(row("t1")).not.toHaveAttribute("aria-current");
    const lines = onModelContext.mock.calls.map(([line]) => String(line));
    expect(lines.filter((line) => line.includes("Task t1"))).toHaveLength(1);
    expect(lines.filter((line) => line.includes("Task t2"))).toHaveLength(1);
  });

  it("keeps the focus on the row a click opened, and gives it back to the row when Esc closes the detail", () => {
    setup(1440);
    const button = screen.getByRole("button", { name: "Task t2" });
    button.focus();
    fireEvent.click(button);
    expect(button).toHaveFocus();
    fireEvent.keyDown(window, { key: "Escape" });
    expect(document.querySelector(".sk-split")).toHaveAttribute(
      "data-split",
      "aside",
    );
    expect(button).toHaveFocus();
  });

  it("moves the focus to the detail's heading when the row was opened with Enter", () => {
    setup(1440);
    const button = screen.getByRole("button", { name: "Task t1" });
    button.focus();
    fireEvent.keyDown(button, { key: "Enter" });
    fireEvent.click(button);
    expect(screen.getByRole("heading", { name: "Title t1" })).toHaveFocus();
  });

  it("asks before a step through the list drops unsaved edits, and keeps them on Fortsätt redigera", () => {
    setup(1440);
    openTask("t1");
    fireEvent.input(screen.getByRole("textbox", { name: "Note" }), {
      target: { value: "half a thought" },
    });
    openTask("t2");
    expect(screen.getByText("Släng ändringarna?")).toBeVisible();
    expect(screen.getByRole("heading", { name: "Title t1" })).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Fortsätt redigera" }));
    expect(screen.getByRole("textbox", { name: "Note" })).toHaveValue(
      "half a thought",
    );
    openTask("t3");
    fireEvent.click(screen.getByRole("button", { name: "Släng" }));
    expect(screen.getByRole("heading", { name: "Title t3" })).toBeVisible();
    expect(panes()).toHaveLength(2);
  });

  it("asks before the × drops unsaved edits", () => {
    setup(1440);
    openTask("t1");
    fireEvent.input(screen.getByRole("textbox", { name: "Note" }), {
      target: { value: "x" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Stäng uppgiften" }));
    expect(screen.getByText("Släng ändringarna?")).toBeVisible();
    fireEvent.click(screen.getByRole("button", { name: "Släng" }));
    expect(screen.queryByRole("heading", { name: "Title t1" })).toBeNull();
    expect(row("t1")?.querySelector("button")).toHaveFocus();
  });

  it("does not take Esc with nothing open, so the host may leave fullscreen with it", () => {
    setup(1440);
    const event = new KeyboardEvent("keydown", {
      key: "Escape",
      bubbles: true,
      cancelable: true,
    });
    act(() => {
      window.dispatchEvent(event);
    });
    expect(event.defaultPrevented).toBe(false);
  });
});

describe("below 64rem", () => {
  it("draws the record alone with the shell's Back row, as before", () => {
    setup(1023);
    expect(document.querySelector(".sk-split")).toHaveAttribute(
      "data-split",
      "single",
    );
    expect(
      screen.queryByRole("complementary", {
        name: "Välj en uppgift för att se den här",
      }),
    ).toBeNull();
    openTask("t1");
    expect(panes()).toHaveLength(1);
    expect(panes()[0]).not.toHaveAttribute("data-pane");
    expect(
      screen.getByRole("button", { name: "Tillbaka till Agenda" }),
    ).toBeVisible();
    expect(screen.getByRole("heading", { name: "Title t1" })).toHaveFocus();
    // Esc is the host's: the shell's Back row is the way back here.
    fireEvent.keyDown(window, { key: "Escape" });
    expect(screen.getByRole("heading", { name: "Title t1" })).toBeVisible();
  });

  it("gives the focus back to the row of the record Back leaves, not to the list's heading", () => {
    setup(1023);
    openTask("t2");
    fireEvent.click(
      screen.getByRole("button", { name: "Tillbaka till Agenda" }),
    );
    expect(screen.getByRole("button", { name: "Task t2" })).toHaveFocus();
  });
});
