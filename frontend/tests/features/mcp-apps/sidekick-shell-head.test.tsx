import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import { sidekickShellLabelsSv } from "@/features/mcp-apps/sidekick-shell-labels";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS } from "@/features/mcp-apps/router";
import { RoomHead } from "@/features/mcp-apps/ui/room-head";
import { useRoomShortcuts } from "@/features/mcp-apps/ui/shortcut-registry";

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

const names = sidekickShellLabelsSv.rooms;

/** A room that draws a head (tabs, + and a ⋯) and one key of its own, as the real rooms do. */
function Stub(props: ShellRoomProps) {
  const room = props.entry.room;
  useRoomShortcuts(
    { j: () => {} },
    {
      id: `${room}-list`,
      title: names[room],
      labels: { j: `Next in ${room}` },
    },
  );
  return (
    <div data-testid={`room-${room}`}>
      <RoomHead
        scope={`sidekick-${room}`}
        keysTitle={names[room]}
        tabs={<div role="group" aria-label={`Views of ${room}`} />}
        add={{ label: `New in ${room}`, onPress: () => {} }}
        more={
          <button type="button" className="sk-iconbtn sk-room-head__tool">
            {`More of ${room}`}
          </button>
        }
      />
    </div>
  );
}

const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;

const start: NavEntry = { room: "work", view: "agenda" };

/** The frame (`.sk-frame`) reports this width; any other element reports 0, as jsdom does. */
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

function setup(over: Partial<Parameters<typeof SidekickShell>[0]> = {}) {
  return render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
      onModelContext={vi.fn()}
      onSendMessage={vi.fn().mockResolvedValue(true)}
      {...over}
    />,
  );
}

function pane(room: string) {
  return document.querySelector<HTMLElement>(`[data-room="${room}"]`);
}

function key(target: Element | Window, name: string) {
  fireEvent.keyDown(target, { key: name });
}

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

describe("the shell's head", () => {
  it("draws the room's head in the bar's row in a wide frame", () => {
    stubFrameWidth(1440);
    setup();
    const shell = document.querySelector(".sk-rooms-shell");
    expect(shell).toHaveAttribute("data-head", "on");
    const slot = document.querySelector<HTMLElement>(
      ".sk-rooms__bar .sk-rooms__head",
    );
    expect(slot).not.toBeNull();
    // The head of the room on top is in the bar, inside the room's scope, and not where the room stands.
    const row = slot?.querySelector(".sidekick-work .sk-room-head");
    expect(row).toHaveAttribute("data-place", "bar");
    expect(
      within(slot as HTMLElement).getByRole("button", { name: "New in work" }),
    ).toBeInTheDocument();
    expect(pane("work")?.querySelector(".sk-room-head")).toBeNull();
    // The strip comes before the head.
    const bar = document.querySelector(".sk-rooms__bar");
    expect(bar?.firstElementChild).toBe(bar?.querySelector(".sk-rooms"));
    expect(slot?.previousElementSibling).toBe(bar?.querySelector(".sk-rooms"));
  });

  it("moves the head with the room: the other room's head is drawn in the same slot", () => {
    stubFrameWidth(1440);
    setup();
    fireEvent.click(screen.getByRole("button", { name: names.journal }));
    const slot = document.querySelector<HTMLElement>(".sk-rooms__head");
    expect(slot?.querySelector(".sidekick-journal")).not.toBeNull();
    expect(slot?.querySelector(".sidekick-work")).toBeNull();
    expect(
      within(slot as HTMLElement).getByRole("button", {
        name: "New in journal",
      }),
    ).toBeInTheDocument();
  });

  it("has no slot in a narrow frame, where the head stands in the room", () => {
    stubFrameWidth(390);
    setup();
    expect(document.querySelector(".sk-rooms__head")).toBeNull();
    expect(document.querySelector(".sk-rooms-shell")).not.toHaveAttribute(
      "data-head",
    );
    const row = pane("work")?.querySelector(".sk-room-head");
    expect(row).toHaveAttribute("data-place", "room");
  });

  it("has no slot just below 64rem and one at exactly 64rem", () => {
    stubFrameWidth(1023);
    const below = setup();
    expect(document.querySelector(".sk-rooms__head")).toBeNull();
    below.unmount();
    stubFrameWidth(1024);
    setup();
    expect(document.querySelector(".sk-rooms__head")).not.toBeNull();
  });

  it("has no slot in an inline card", () => {
    stubFrameWidth(1440);
    setup({ full: false });
    expect(document.querySelector(".sk-rooms__head")).toBeNull();
  });
});

describe("the shell's global keys", () => {
  it("opens the help on ?, lists Överallt first and the room's own group, and closes on Esc with the focus back", () => {
    stubFrameWidth(1440);
    setup();
    const tab = screen.getByRole("button", { name: names.work });
    tab.focus();
    key(tab, "?");
    const dialog = screen.getByRole("dialog", { name: "Kortkommandon" });
    const headings = within(dialog)
      .getAllByRole("heading")
      .map((heading) => heading.textContent);
    expect(headings[0]).toBe("Kortkommandon");
    expect(headings.slice(1)).toEqual(["Överallt", names.work]);
    // The room's head keys and its list keys share one heading.
    expect(within(dialog).getByText("New in work")).toBeInTheDocument();
    expect(within(dialog).getByText("Next in work")).toBeInTheDocument();
    expect(
      within(dialog).getByText(
        sidekickShellLabelsSv.shortcuts.goTo(names.shopping),
      ),
    ).toBeInTheDocument();
    expect(
      within(dialog).getByText(sidekickShellLabelsSv.shortcuts.openMore),
    ).toBeInTheDocument();

    key(within(dialog).getByRole("button", { name: "Stäng" }), "Escape");
    expect(dialog).not.toHaveAttribute("open");
    expect(document.activeElement).toBe(tab);
  });

  it("lists the help in English for an English app", () => {
    stubFrameWidth(1440);
    setup({ locale: "en" });
    key(window, "?");
    const dialog = screen.getByRole("dialog", { name: "Keyboard shortcuts" });
    expect(
      within(dialog).getByRole("heading", { name: "Everywhere" }),
    ).toBeInTheDocument();
  });

  it("changes room on g and a number, in the strip's order, and g 6 opens Mer", () => {
    stubFrameWidth(1440);
    setup();
    expect(screen.getByRole("button", { name: names.work })).toHaveAttribute(
      "aria-current",
      "page",
    );
    key(window, "g");
    key(window, "1");
    expect(screen.getByRole("button", { name: names.start })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(pane("start")).not.toHaveAttribute("hidden");
    key(window, "g");
    key(window, "3");
    expect(screen.getByRole("button", { name: names.journal })).toHaveAttribute(
      "aria-current",
      "page",
    );
    expect(pane("journal")).not.toHaveAttribute("hidden");
    expect(pane("start")).toHaveAttribute("hidden");
    key(window, "g");
    key(window, "4");
    expect(
      screen.getByRole("button", { name: names.shopping }),
    ).toHaveAttribute("aria-current", "page");
    // There is no g 5: the number does nothing, and g 6 opens the Mer menu instead.
    key(window, "g");
    key(window, "5");
    expect(
      screen.getByRole("button", { name: names.shopping }),
    ).toHaveAttribute("aria-current", "page");
    key(window, "g");
    key(window, "6");
    expect(screen.getByRole("button", { name: "Mer" })).toHaveAttribute(
      "aria-expanded",
      "true",
    );
  });

  it("works in a narrow frame too, but ? and g are off in an inline card", () => {
    stubFrameWidth(390);
    const wide = setup();
    key(window, "g");
    key(window, "4");
    expect(
      screen.getByRole("button", { name: names.shopping }),
    ).toHaveAttribute("aria-current", "page");
    wide.unmount();

    stubFrameWidth(1440);
    setup({ full: false });
    key(window, "?");
    key(window, "g");
    key(window, "2");
    expect(screen.queryByRole("dialog")).toBeNull();
    expect(screen.queryByRole("navigation")).toBeNull();
    expect(document.querySelector("dialog")).toBeNull();
  });

  it("does not take ? or g typed into a field", () => {
    stubFrameWidth(1440);
    setup();
    const field = document.createElement("input");
    document.body.append(field);
    key(field, "?");
    key(field, "g");
    key(field, "2");
    expect(document.querySelector("dialog[open]")).toBeNull();
    expect(screen.getByRole("button", { name: names.work })).toHaveAttribute(
      "aria-current",
      "page",
    );
    field.remove();
  });
});
