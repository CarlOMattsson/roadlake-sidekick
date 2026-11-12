import { act, cleanup, render, screen } from "@testing-library/react";
import { afterEach, expect, it } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import { enabledRooms, roomEnabled } from "@/features/mcp-apps/enabled-rooms";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";

// SIDEKICK_ENABLED_ROOMS arrives as a meta tag in the app document. A room that is off is left out of the
// strip and the picker, and a cross link to it leads nowhere.
const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

let seen: Partial<Record<RoomId, ShellRoomProps>> = {};
function record(props: ShellRoomProps) {
  seen[props.entry.room] = props;
}
function Stub(props: ShellRoomProps) {
  record(props);
  return <h2>{`${props.entry.room}/${props.entry.view}`}</h2>;
}
const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;
const start: NavEntry = { room: "work", view: "agenda" };

function declare(content: string | undefined) {
  document.head.innerHTML =
    content === undefined
      ? ""
      : `<meta name="sidekick-rooms" content="${content}">`;
}
function stripNames(): string[] {
  const nav = screen.queryByRole("navigation", { name: "Rum" });
  return nav
    ? Array.from(nav.querySelectorAll("button")).map((b) => b.textContent ?? "")
    : [];
}
function setup() {
  return render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
    />,
  );
}

afterEach(() => {
  cleanup();
  seen = {};
  declare(undefined);
});

it("is every room when the document declares nothing", () => {
  declare(undefined);
  expect(enabledRooms()).toEqual(ROOM_IDS);
  expect(roomEnabled("journal")).toBe(true);
});

it("reads the declared rooms and always keeps work", () => {
  declare("journal, control");
  expect(enabledRooms()).toEqual(["work", "journal", "control"]);
  expect(roomEnabled("contacts")).toBe(false);
  declare("kitchen");
  expect(enabledRooms()).toEqual(["work"]);
});

it("shows every strip room when all are on", () => {
  declare("work,journal,shopping,contacts,control");
  setup();
  expect(stripNames()).toEqual(["Arbete", "Dagbok", "Kontakter", "Inköp"]);
});

it("leaves the rooms that are off out of the strip", () => {
  declare("work,shopping");
  setup();
  expect(stripNames()).toEqual(["Arbete", "Inköp"]);
});

it("draws no strip at all when only Arbete is on", () => {
  declare("work");
  setup();
  expect(screen.queryByRole("navigation", { name: "Rum" })).toBeNull();
  expect(screen.getByRole("heading", { name: "work/agenda" })).toBeVisible();
});

it("ignores a cross link to a room that is off and keeps the room it is in", () => {
  declare("work,shopping");
  setup();
  act(() =>
    seen.work?.navigate?.({ room: "contacts", view: "contact", id: "c1" }),
  );
  expect(
    screen.queryByRole("heading", { name: "contacts/contact" }),
  ).toBeNull();
  expect(screen.getByRole("heading", { name: "work/agenda" })).toBeVisible();
  act(() => seen.work?.navigate?.({ room: "shopping", view: "lists" }));
  expect(screen.getByRole("heading", { name: "shopping/lists" })).toBeVisible();
});
