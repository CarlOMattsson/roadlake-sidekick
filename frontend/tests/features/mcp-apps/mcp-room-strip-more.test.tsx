import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import {
  sidekickShellLabelsEn,
  sidekickShellLabelsSv,
} from "@/features/mcp-apps/sidekick-shell-labels";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { MenuItem } from "@/features/mcp-apps/ui/menu";
import {
  MORE_ROOM_IDS,
  PRIMARY_ROOM_IDS,
  ROOM_IDS,
  STRIP_ROOM_IDS,
  type RoomId,
} from "@/features/mcp-apps/router";

// The strip's rooms used several times a week have cells of their own; Contacts, used about once a week, is a row of
// the last cell, Mer ⌄. jsdom has no fine pointer and a 0 wide frame, so Mer's menu is the phone's panel here.
const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};
const RESERVE: HostFeatures = {
  serverTools: false,
  message: true,
  openLinks: false,
};

function Stub(props: ShellRoomProps) {
  return (
    <div data-testid={`room-${props.entry.room}`}>
      <h2>{`${props.entry.room}/${props.entry.view}`}</h2>
    </div>
  );
}
const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;
const workStart: NavEntry = { room: "work", view: "agenda" };

function setup(
  over: Partial<Parameters<typeof SidekickShell>[0]> = {},
  start: NavEntry = workStart,
) {
  const onSendMessage = vi.fn().mockResolvedValue(true);
  const utils = render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
      onSendMessage={onSendMessage}
      {...over}
    />,
  );
  return { ...utils, onSendMessage };
}
function strip() {
  return screen.getByRole("navigation", { name: "Rum" });
}
function cellNames(): string[] {
  return Array.from(
    strip().querySelectorAll(".sk-rooms__tab"),
    (cell) => cell.textContent ?? "",
  );
}
function moreCell() {
  return strip().querySelector<HTMLButtonElement>(".sk-rooms__more");
}
function pane(room: RoomId) {
  return document.querySelector<HTMLElement>(`[data-room="${room}"]`);
}
function declare(content: string | undefined) {
  document.head.innerHTML =
    content === undefined
      ? ""
      : `<meta name="sidekick-rooms" content="${content}">`;
}

beforeEach(() => {
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  declare(undefined);
});

it("keeps the strip's rooms in a fixed order: the cells, then the rows of Mer", () => {
  expect(PRIMARY_ROOM_IDS).toEqual(["work", "journal", "shopping"]);
  expect(MORE_ROOM_IDS).toEqual(["contacts"]);
  expect(STRIP_ROOM_IDS).toEqual([...PRIMARY_ROOM_IDS, ...MORE_ROOM_IDS]);
});

it.each([
  ["sv", "Rum", ["Arbete", "Dagbok", "Inköp", "Mer"]],
  ["en", "Rooms", ["Work", "Journal", "Shopping", "More"]],
] as const)(
  "draws three rooms and Mer last in %s, with Contacts out of the cells",
  (locale, label, names) => {
    setup({ locale });
    const nav = screen.getByRole("navigation", { name: label });
    expect(
      Array.from(
        nav.querySelectorAll(".sk-rooms__tab"),
        (cell) => cell.textContent,
      ),
    ).toEqual(names);
    const more = nav.querySelector(".sk-rooms__more")!;
    expect(more).toHaveAttribute("aria-expanded", "false");
    expect(more).not.toHaveAttribute("aria-current");
    // Mer has the strip's roving focus: one tab stop, on the room shown.
    expect(more).toHaveAttribute("tabindex", "-1");
  },
);

it("opens Mer on a press and switches to Contacts without a model turn; the cell then carries its name", () => {
  const { onSendMessage } = setup();
  fireEvent.click(moreCell()!);
  expect(moreCell()).toHaveAttribute("aria-expanded", "true");
  const menu = screen.getByRole("group", { name: "Fler rum" });
  expect(menu).toHaveAttribute("id", moreCell()!.getAttribute("aria-controls"));
  const row = within(menu).getByRole("button", { name: "Kontakter" });
  expect(row).not.toHaveAttribute("aria-current");
  fireEvent.click(row);

  expect(screen.queryByRole("group", { name: "Fler rum" })).toBeNull();
  expect(pane("contacts")).not.toHaveAttribute("hidden");
  expect(onSendMessage).not.toHaveBeenCalled();
  expect(cellNames()).toEqual(["Arbete", "Dagbok", "Inköp", "Kontakter"]);
  const more = moreCell()!;
  expect(more).toHaveAttribute("aria-current", "page");
  expect(more).toHaveAccessibleName("Kontakter, Mer");
  expect(more).toHaveAttribute("tabindex", "0");
  expect(screen.getByRole("button", { name: "Arbete" })).toHaveAttribute(
    "tabindex",
    "-1",
  );
  // The room's heading takes the focus, as after any room change.
  expect(pane("contacts")?.querySelector("h2")).toHaveFocus();

  // Opened again, the menu ticks the room the user is in.
  fireEvent.click(more);
  expect(
    within(screen.getByRole("group", { name: "Fler rum" })).getByRole(
      "button",
      { name: "Kontakter" },
    ),
  ).toHaveAttribute("aria-current", "page");
});

it("leads back from a room of Mer by the room's own cell", () => {
  setup({}, { room: "contacts", view: "list" });
  expect(moreCell()).toHaveAttribute("aria-current", "page");
  fireEvent.click(screen.getByRole("button", { name: "Inköp" }));
  expect(pane("shopping")).not.toHaveAttribute("hidden");
  expect(moreCell()).toHaveTextContent(/^Mer$/);
  expect(moreCell()).not.toHaveAttribute("aria-current");
});

it("marks no room on Mer in Control", () => {
  setup({}, { room: "control", view: "trash" });
  expect(moreCell()).toHaveTextContent(/^Mer$/);
  expect(moreCell()).not.toHaveAttribute("aria-current");
});

it("opens with ↓ on the first room and closes on Escape with the focus back on Mer", () => {
  setup();
  const more = moreCell()!;
  more.focus();
  fireEvent.keyDown(more, { key: "ArrowDown" });
  const row = within(screen.getByRole("group", { name: "Fler rum" })).getByRole(
    "button",
    { name: "Kontakter" },
  );
  // ↓ opens the menu: the strip's roving focus does not move on to another cell.
  expect(row).toHaveFocus();
  fireEvent.keyDown(row, { key: "Escape" });
  expect(screen.queryByRole("group", { name: "Fler rum" })).toBeNull();
  expect(more).toHaveFocus();
});

it("closes the panel on a press outside it, with nothing chosen", () => {
  setup();
  fireEvent.click(moreCell()!);
  fireEvent.pointerDown(screen.getByRole("heading", { name: "work/agenda" }));
  expect(screen.queryByRole("group", { name: "Fler rum" })).toBeNull();
  expect(pane("work")).not.toHaveAttribute("hidden");
});

it("opens Mer on g 5 with the focus on its first room, and lists the key in the help", () => {
  setup();
  fireEvent.keyDown(window, { key: "g" });
  fireEvent.keyDown(window, { key: "5" });
  expect(
    within(screen.getByRole("group", { name: "Fler rum" })).getByRole(
      "button",
      { name: "Kontakter" },
    ),
  ).toHaveFocus();
  fireEvent.keyDown(document.activeElement!, { key: "Escape" });

  fireEvent.keyDown(window, { key: "?" });
  const help = screen.getByRole("dialog");
  expect(help).toHaveTextContent("Öppna Mer");
  // The rooms with a cell keep g 1–g 3 in the strip's order.
  expect(help).toHaveTextContent("Gå till Inköp");
  expect(help).not.toHaveTextContent("Gå till Kontakter");
});

it("draws no Mer when none of its rooms is on, and g 5 does nothing", () => {
  declare("work,journal,shopping");
  setup();
  expect(cellNames()).toEqual(["Arbete", "Dagbok", "Inköp"]);
  expect(moreCell()).toBeNull();
  fireEvent.keyDown(window, { key: "g" });
  fireEvent.keyDown(window, { key: "5" });
  expect(screen.queryByRole("group", { name: "Fler rum" })).toBeNull();
});

it("draws no Mer when the host offers no room for it (the phone)", () => {
  setup({ primaryRooms: ["work", "journal", "shopping"], moreRooms: [] });
  expect(cellNames()).toEqual(["Arbete", "Dagbok", "Inköp"]);
  expect(moreCell()).toBeNull();
});

it("keeps the strip with Work and Mer alone, since they lead to two rooms", () => {
  declare("work,contacts");
  setup();
  expect(cellNames()).toEqual(["Arbete", "Mer"]);
});

it("asks Claude for a room of Mer on a host that cannot call tools", async () => {
  const { onSendMessage } = setup({ features: RESERVE });
  fireEvent.click(moreCell()!);
  fireEvent.click(screen.getByRole("button", { name: "Kontakter" }));
  expect(onSendMessage).toHaveBeenCalledWith("Öppna Kontakter");
  // The note after the host accepted the message.
  expect(await screen.findByText("Bad Claude öppna Kontakter")).toBeVisible();
});

it("lists the rooms of Mer last in the narrow room picker", () => {
  vi.spyOn(HTMLElement.prototype, "scrollWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("sk-rooms__tabs") ? 400 : 0;
    },
  );
  vi.spyOn(HTMLElement.prototype, "clientWidth", "get").mockImplementation(
    function (this: HTMLElement) {
      return this.classList.contains("sk-rooms__tabs") ? 280 : 0;
    },
  );
  setup();
  fireEvent.click(
    document.querySelector<HTMLButtonElement>(".sk-rooms .sk-pick")!,
  );
  expect(
    screen.getAllByRole("menuitemradio").map((item) => item.textContent),
  ).toEqual(["Arbete", "Dagbok", "Inköp", "Kontakter"]);
  vi.restoreAllMocks();
});

it("has the same Mer words in both app languages", () => {
  for (const labels of [sidekickShellLabelsSv, sidekickShellLabelsEn]) {
    expect(labels.more).not.toBe("");
    expect(labels.moreMenu).not.toBe("");
    expect(labels.moreWith("X")).toContain(labels.more);
    expect(labels.shortcuts.openMore).toContain(labels.more);
  }
  expect(sidekickShellLabelsEn.more).toBe("More");
});

it("draws a menu entry's meta line under its name, and ticks the current one", () => {
  render(
    <div>
      <MenuItem label="Bibliotek" meta="4 att läsa" onChoose={() => {}} />
      <MenuItem label="Kontakter" current onChoose={() => {}} />
    </div>,
  );
  const withMeta = screen.getByRole("button", { name: "Bibliotek 4 att läsa" });
  expect(withMeta.querySelector(".sk-menu-item__meta")).toHaveTextContent(
    "4 att läsa",
  );
  expect(withMeta).not.toHaveAttribute("aria-current");
  expect(screen.getByRole("button", { name: "Kontakter" })).toHaveAttribute(
    "aria-current",
    "page",
  );
});
