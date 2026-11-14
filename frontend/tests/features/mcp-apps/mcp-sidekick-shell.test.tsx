import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import { useEffect, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  modelContextLine,
  STALE_AFTER_MS,
  type ShellRoomProps,
  type RoomRegistry,
} from "@/features/mcp-apps/sidekick-shell";
import {
  sidekickShellLabelsEn,
  sidekickShellLabelsSv,
} from "@/features/mcp-apps/sidekick-shell-labels";
import { STACK_LIMIT, type NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";

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
const NOTHING: HostFeatures = {
  serverTools: false,
  message: false,
  openLinks: false,
};

/** Latest props each stub room was drawn with, and how often each was mounted. */
let seen: Partial<Record<RoomId, ShellRoomProps>>;

function record(props: ShellRoomProps) {
  seen[props.entry.room] = props;
}
function Stub(props: ShellRoomProps) {
  record(props);
  return (
    <div data-testid={`room-${props.entry.room}`}>
      <h2>{`${props.entry.room}/${props.entry.view}/${props.entry.id ?? "-"}`}</h2>
      <span data-testid={`refresh-${props.entry.room}`}>
        {props.refreshKey}
      </span>
      <span data-testid={`full-${props.entry.room}`}>{String(props.full)}</span>
    </div>
  );
}
const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;

const journalStart: NavEntry = {
  room: "journal",
  view: "day",
  id: "2026-11-03",
};

function setup(
  over: Partial<Parameters<typeof SidekickShell>[0]> = {},
  start: NavEntry = journalStart,
) {
  const onModelContext = vi.fn();
  const onSendMessage = vi.fn().mockResolvedValue(true);
  const utils = render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={start}
      full
      features={LOCAL}
      onModelContext={onModelContext}
      onSendMessage={onSendMessage}
      {...over}
    />,
  );
  return { ...utils, onModelContext, onSendMessage };
}

/** The strip button for a room. */
function tab(name: string) {
  return screen.getByRole("button", { name });
}
/** The pane of the strip room `room`, even when hidden. */
function pane(room: RoomId) {
  return document.querySelector<HTMLElement>(`[data-room="${room}"]`);
}
function navigateTo(target: NavEntry, from: RoomId) {
  act(() => seen[from]?.navigate?.(target));
}

beforeEach(() => {
  seen = {};
  localStorage.clear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("draws only the start room, with no strip, in an inline card", () => {
  const { onModelContext } = setup({ full: false });
  expect(screen.getByTestId("room-journal")).toBeInTheDocument();
  expect(screen.getByTestId("full-journal")).toHaveTextContent("false");
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(seen.journal?.navigate).toBeUndefined();
  expect(onModelContext).not.toHaveBeenCalled();
});

it("shows the four strip rooms in order, marks the active one, and leaves Control out", () => {
  setup();
  const nav = screen.getByRole("navigation", { name: "Rum" });
  const names = Array.from(nav.querySelectorAll("button")).map(
    (b) => b.textContent,
  );
  expect(names).toEqual(["Arbete", "Dagbok", "Kontakter", "Inköp"]);
  expect(tab("Dagbok")).toHaveAttribute("aria-current", "page");
  expect(tab("Arbete")).not.toHaveAttribute("aria-current");
  expect(screen.queryByRole("button", { name: "Kontroll" })).toBeNull();
});

it("uses English labels for an English app", () => {
  setup({ locale: "en" });
  expect(screen.getByRole("navigation", { name: "Rooms" })).toBeInTheDocument();
  expect(tab("Journal")).toBeInTheDocument();
  expect(tab("Shopping")).toBeInTheDocument();
});

it("mounts a room on its first visit only and keeps it mounted, hidden, afterwards", () => {
  setup();
  expect(pane("work")).toBeNull();
  fireEvent.click(tab("Arbete"));
  expect(pane("work")).not.toBeNull();
  expect(pane("work")).not.toHaveAttribute("hidden");
  expect(pane("journal")).toHaveAttribute("hidden");
  fireEvent.click(tab("Dagbok"));
  expect(pane("work")).toHaveAttribute("hidden");
  expect(screen.getByTestId("room-work")).toBeInTheDocument();
});

it("keeps one stack per room across room changes", () => {
  setup();
  navigateTo(
    { room: "contacts", view: "contact", id: "c1", label: "Anna" },
    "journal",
  );
  expect(
    screen.getByRole("heading", { name: "contacts/contact/c1" }),
  ).toBeVisible();
  fireEvent.click(tab("Arbete"));
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
  fireEvent.click(tab("Dagbok"));
  // The journal pane still shows Anna, and the strip still says Dagbok.
  expect(
    screen.getByRole("heading", { name: "contacts/contact/c1" }),
  ).toBeVisible();
  expect(tab("Dagbok")).toHaveAttribute("aria-current", "page");
});

it("keeps the room under a cross-link mounted with its state, so Back restores it", () => {
  const mounts: string[] = [];
  function Stateful(props: ShellRoomProps) {
    record(props);
    const [draft, setDraft] = useState("");
    useEffect(() => {
      mounts.push(props.entry.room);
    }, [props.entry.room]);
    return (
      <div>
        <h2>{`${props.entry.room}/${props.entry.view}`}</h2>
        <input
          aria-label={`draft-${props.entry.room}`}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
        />
      </div>
    );
  }
  const stateful = Object.fromEntries(
    ROOM_IDS.map((room) => [room, Stateful]),
  ) as RoomRegistry;
  setup({ rooms: stateful });
  // `input`, not `change`: Preact (the bundle) maps onChange to the input event, as a real keystroke fires it.
  fireEvent.input(screen.getByLabelText("draft-journal"), {
    target: { value: "osparat utkast" },
  });
  navigateTo({ room: "contacts", view: "contact", id: "c1" }, "journal");
  expect(screen.getByLabelText("draft-journal")).not.toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  // The journal room was never unmounted: same input value, mounted once.
  expect(screen.getByLabelText("draft-journal")).toHaveValue("osparat utkast");
  expect(mounts.filter((room) => room === "journal")).toHaveLength(1);
});

it("shows Back only when the active room has something to go back to", () => {
  setup();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
  navigateTo({ room: "contacts", view: "contact", id: "c1" }, "journal");
  navigateTo({ room: "work", view: "task", id: "t1" }, "contacts");
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  expect(
    screen.getByRole("heading", { name: "contacts/contact/c1" }),
  ).toBeVisible();
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  expect(
    screen.getByRole("heading", { name: "journal/day/2026-11-03" }),
  ).toBeVisible();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
});

it("goes to the room's root when the active room is pressed", () => {
  setup();
  navigateTo({ room: "contacts", view: "contact", id: "c1" }, "journal");
  navigateTo({ room: "work", view: "task", id: "t1" }, "contacts");
  fireEvent.click(tab("Dagbok"));
  expect(
    screen.getByRole("heading", { name: "journal/day/2026-11-03" }),
  ).toBeVisible();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
});

it("ignores the same target twice in a row and caps the stack at eight", () => {
  setup();
  const target: NavEntry = { room: "contacts", view: "contact", id: "c1" };
  navigateTo(target, "journal");
  navigateTo(target, "contacts");
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();

  for (let i = 0; i < STACK_LIMIT + 3; i += 1)
    navigateTo(
      { room: "work", view: "task", id: `t${i}` },
      i === 0 ? "journal" : "work",
    );
  let backs = 0;
  while (screen.queryByRole("button", { name: /^Tillbaka/ })) {
    fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
    backs += 1;
  }
  expect(backs).toBe(STACK_LIMIT);
});

it("uses no window.history and stores nothing in localStorage", () => {
  const push = vi.spyOn(window.history, "pushState");
  const replace = vi.spyOn(window.history, "replaceState");
  setup();
  navigateTo(
    { room: "contacts", view: "contact", id: "c1", label: "Anna" },
    "journal",
  );
  fireEvent.click(tab("Kontakter"));
  fireEvent.click(tab("Inköp"));
  expect(push).not.toHaveBeenCalled();
  expect(replace).not.toHaveBeenCalled();
  expect(localStorage.length).toBe(0);
});

it("re-reads a room another room wrote to, but not the room that wrote", () => {
  setup({}, { room: "work", view: "agenda" });
  fireEvent.click(tab("Dagbok"));
  expect(screen.getByTestId("refresh-journal")).toHaveTextContent("0");
  // A journal draft turned into a task: the journal pane marks the work domain dirty.
  act(() => seen.journal?.markDirty(["work"]));
  fireEvent.click(tab("Arbete"));
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("1");
  fireEvent.click(tab("Dagbok"));
  // The writer's own pane is up to date, and the work pane has now seen the write.
  expect(screen.getByTestId("refresh-journal")).toHaveTextContent("0");
  fireEvent.click(tab("Arbete"));
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("1");
});

it("re-reads the layer under the top when Back returns to it after a write above it", () => {
  setup({}, { room: "work", view: "agenda" });
  navigateTo({ room: "work", view: "task", id: "t1" }, "work");
  // Agenda (the root) and the task are both mounted; the task is the layer that writes.
  expect(screen.getAllByTestId("refresh-work")).toHaveLength(2);
  act(() => seen.work?.markDirty(["work", "contacts"]));
  // Nothing is read while the agenda is hidden, and the writing layer is not asked to read.
  expect(
    screen.getAllByTestId("refresh-work").map((el) => el.textContent),
  ).toEqual(["0", "0"]);
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  // The agenda is shown again: it reads once, in the same layer, with its view kept.
  expect(screen.getAllByTestId("refresh-work")).toHaveLength(1);
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("1");
});

it("re-reads the layer under the top in another room after a write there", () => {
  setup({}, { room: "work", view: "agenda" });
  navigateTo({ room: "work", view: "task", id: "t1" }, "work");
  fireEvent.click(tab("Dagbok"));
  // A write from the journal while Work is hidden: nothing is read until Work is shown.
  act(() => seen.journal?.markDirty(["work"]));
  expect(
    screen.getAllByTestId("refresh-work").map((el) => el.textContent),
  ).toEqual(["0", "0"]);
  fireEvent.click(tab("Arbete"));
  expect(
    screen.getAllByTestId("refresh-work").map((el) => el.textContent),
  ).toEqual(["0", "1"]);
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  // The agenda under it saw the same write when it is shown.
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("1");
});

it("re-reads a room that was hidden for more than 60 seconds, not before", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(1_000_000);
  setup({}, { room: "work", view: "agenda" });
  fireEvent.click(tab("Dagbok"));
  fireEvent.click(tab("Arbete"));
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("0");
  fireEvent.click(tab("Dagbok"));
  vi.setSystemTime(1_000_000 + STALE_AFTER_MS + 1);
  fireEvent.click(tab("Arbete"));
  expect(screen.getByTestId("refresh-work")).toHaveTextContent("1");
});

// A card opened on a record: the day under it was never shown, so it has no hidden time of its own.
it("re-reads a root that was never shown when Back reaches it after more than 60 seconds", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(1_000_000);
  setup({ openAt: { room: "journal", view: "entry", id: "e1" } });
  vi.setSystemTime(1_000_000 + STALE_AFTER_MS + 1);
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  expect(screen.getByTestId("refresh-journal")).toHaveTextContent("1");
});

it("does not re-read a root that was never shown before a minute has passed", () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(1_000_000);
  setup({ openAt: { room: "journal", view: "entry", id: "e1" } });
  vi.setSystemTime(1_000_000 + STALE_AFTER_MS - 1000);
  fireEvent.click(screen.getByRole("button", { name: /^Tillbaka/ }));
  expect(screen.getByTestId("refresh-journal")).toHaveTextContent("0");
});

it("tells the model where the user is on start, on a room change and on a cross-link", () => {
  const { onModelContext } = setup();
  expect(onModelContext).toHaveBeenLastCalledWith(
    "Visar Dagbok (id 2026-11-03)",
  );
  fireEvent.click(tab("Kontakter"));
  expect(onModelContext).toHaveBeenLastCalledWith("Visar Kontakter");
  fireEvent.click(tab("Dagbok"));
  navigateTo(
    { room: "contacts", view: "contact", id: "c1", label: "Anna Andersson" },
    "journal",
  );
  expect(onModelContext).toHaveBeenLastCalledWith(
    "Visar Dagbok › Kontakter › Anna Andersson (id c1)",
  );
});

it("never puts journal text in the model context and keeps the line short", () => {
  const entry: NavEntry = {
    room: "journal",
    view: "entry",
    id: "e1",
    label: "Hemlig dagbokstext om middagen",
  };
  const line = modelContextLine(sidekickShellLabelsSv, "journal", entry);
  expect(line).toBe("Visar Dagbok (id e1)");
  expect(line).not.toContain("Hemlig");
  const long = modelContextLine(sidekickShellLabelsEn, "contacts", {
    room: "contacts",
    view: "contact",
    id: "c1",
    label: "x".repeat(900),
  });
  expect(long.length).toBeLessThanOrEqual(500);
  expect(long.startsWith("Viewing Contacts")).toBe(true);
});

it("hands rooms a navigate function only when the host can proxy tool calls", () => {
  setup();
  expect(seen.journal?.navigate).toBeTypeOf("function");
  cleanup();
  seen = {};
  setup({ features: RESERVE });
  expect(seen.journal?.navigate).toBeUndefined();
});

it("asks Claude to open the room when the host cannot proxy tools but can take messages", async () => {
  const { onSendMessage } = setup({ features: RESERVE });
  await act(async () => {
    fireEvent.click(tab("Arbete"));
    await Promise.resolve();
  });
  expect(onSendMessage).toHaveBeenCalledWith("Öppna Arbete");
  // Nothing changes locally: the card stays on the journal and no other room mounts.
  expect(tab("Dagbok")).toHaveAttribute("aria-current", "page");
  expect(pane("work")).toBeNull();
  expect(screen.getByRole("status")).toHaveTextContent(
    "Bad Claude öppna Arbete",
  );
  // The active room sends nothing.
  fireEvent.click(tab("Dagbok"));
  expect(onSendMessage).toHaveBeenCalledTimes(1);
});

it("sends the English message for an English app", async () => {
  const { onSendMessage } = setup({ features: RESERVE, locale: "en" });
  await act(async () => {
    fireEvent.click(tab("Contacts"));
    await Promise.resolve();
  });
  expect(onSendMessage).toHaveBeenCalledWith("Open Contacts");
});

it("stays quiet when the host refuses the reserve message", async () => {
  const onSendMessage = vi.fn().mockResolvedValue(false);
  setup({ features: RESERVE, onSendMessage });
  await act(async () => {
    fireEvent.click(tab("Arbete"));
    await Promise.resolve();
  });
  expect(onSendMessage).toHaveBeenCalledTimes(1);
  expect(screen.getByRole("status")).toBeEmptyDOMElement();
});

it("hides the strip when the host has neither tool proxy nor messages", () => {
  setup({ features: NOTHING });
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(screen.getByTestId("room-journal")).toBeInTheDocument();
  expect(seen.journal?.navigate).toBeUndefined();
});

it("opens Control as a step of Arbete: the strip stays with no room chosen, and Back reads 'Tillbaka till Arbete'", () => {
  setup({}, { room: "control", view: "trash" });
  // Control applies to every room, so no room is marked there: the strip stays, with no tab current (designsystem §3,
  // Rumsremsan).
  const strip = screen.getByRole("navigation", { name: "Rum" });
  expect(within(strip).getAllByRole("button")).toHaveLength(4);
  for (const button of within(strip).getAllByRole("button"))
    expect(button).not.toHaveAttribute("aria-current");
  const back = screen.getByRole("button", {
    name: "Tillbaka till Arbete",
  });
  expect(back).toBeInTheDocument();
  // The Back row reads "‹ Arbete", where it leads, like every other Back.
  expect(back).toHaveTextContent("Arbete");
  expect(back.closest(".sk-back-header")).not.toHaveClass(
    "sk-back-header--heading",
  );
  // Control is drawn on the Arbete stack, so its own pane is never made; the room's pane shows it.
  expect(pane("control")).toBeNull();
  expect(
    screen.getByRole("heading", { name: "control/trash/-" }),
  ).toBeVisible();
});

it("Back names the list a record was opened from: 'Projekt' from the Projects tab, 'Agenda' from the agenda", () => {
  setup({}, { room: "work", view: "root" });
  navigateTo(
    { room: "work", view: "project", id: "p1", from: "hierarchy" },
    "work",
  );
  expect(
    screen.getByRole("button", { name: "Tillbaka till Projekt" }),
  ).toBeInTheDocument();
  fireEvent.click(
    screen.getByRole("button", { name: "Tillbaka till Projekt" }),
  );
  navigateTo({ room: "work", view: "task", id: "t1", from: "agenda" }, "work");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Agenda" }),
  ).toBeInTheDocument();
});

it("Back from a record opened by Claude names the room; from a Process or Project below another record, the kind", () => {
  setup({}, { room: "work", view: "root" });
  navigateTo({ room: "work", view: "process", id: "r1" }, "work");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Arbete" }),
  ).toBeInTheDocument();
  // A record below a record without a name of its own: Back names that record's kind.
  navigateTo({ room: "work", view: "task", id: "t1" }, "work");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Process" }),
  ).toBeInTheDocument();
  navigateTo({ room: "work", view: "project", id: "p1" }, "work");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Uppgift" }),
  ).toBeInTheDocument();
});

it("Back from a journal entry's original text names the entry it returns to, not the journal", () => {
  setup({}, journalStart);
  navigateTo({ room: "journal", view: "entry", id: "e1" }, "journal");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Dagbok" }),
  ).toBeInTheDocument();
  navigateTo({ room: "journal", view: "source", id: "s1" }, "journal");
  expect(
    screen.getByRole("button", { name: "Tillbaka till Anteckning" }),
  ).toBeInTheDocument();
});

it("a record below a named record keeps the name of that record in Back, even when it was opened from a list", () => {
  setup({}, { room: "work", view: "root" });
  navigateTo(
    { room: "work", view: "task", id: "t1", label: "Ring Anna" },
    "work",
  );
  navigateTo(
    { room: "work", view: "project", id: "p1", from: "agenda" },
    "work",
  );
  expect(
    screen.getByRole("button", { name: "Tillbaka till Ring Anna" }),
  ).toBeInTheDocument();
});

it("the origin room's tab in the strip takes Control back to that room, as Back does", () => {
  setup({}, { room: "control", view: "trash" });
  fireEvent.click(tab("Arbete"));
  expect(tab("Arbete")).toHaveAttribute("aria-current", "page");
  expect(pane("work")).not.toHaveAttribute("hidden");
  expect(screen.getByRole("heading", { name: "work/root/-" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "control/trash/-" })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
});

it("leaves Control through Back: the work room opens with Arbete marked in the strip again", () => {
  setup({}, { room: "control", view: "trash" });
  fireEvent.click(screen.getByRole("button", { name: "Tillbaka till Arbete" }));
  expect(tab("Arbete")).toHaveAttribute("aria-current", "page");
  expect(pane("work")).not.toHaveAttribute("hidden");
  expect(screen.getByRole("heading", { name: "work/root/-" })).toBeVisible();
  expect(screen.queryByRole("heading", { name: "control/trash/-" })).toBeNull();
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
  expect(screen.queryByRole("button", { name: "Kontroll" })).toBeNull();
});

it("a room that opens Control: the strip stays with no room chosen while Control is open, and Back returns to that room", () => {
  setup();
  navigateTo({ room: "control", view: "trash" }, "journal");
  const strip = screen.getByRole("navigation", { name: "Rum" });
  for (const button of within(strip).getAllByRole("button"))
    expect(button).not.toHaveAttribute("aria-current");
  expect(
    screen.getByRole("heading", { name: "control/trash/-" }),
  ).toBeVisible();
  const backToJournal = screen.getByRole("button", {
    name: "Tillbaka till Dagbok",
  });
  expect(backToJournal).toBeInTheDocument();
  // The row reads "‹ Dagbok", the origin it leads to.
  expect(backToJournal).toHaveTextContent("Dagbok");
  fireEvent.click(backToJournal);
  expect(
    screen.getByRole("heading", { name: "journal/day/2026-11-03" }),
  ).toBeVisible();
  expect(tab("Dagbok")).toHaveAttribute("aria-current", "page");
});

it("offers 'Fäll ihop' only when the caller can fold the expanded view in", () => {
  const onCollapse = vi.fn();
  const { rerender } = setup({ onCollapse });
  fireEvent.click(screen.getByRole("button", { name: "Fäll ihop" }));
  expect(onCollapse).toHaveBeenCalledTimes(1);
  rerender(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={journalStart}
      full
      features={LOCAL}
    />,
  );
  expect(screen.queryByRole("button", { name: "Fäll ihop" })).toBeNull();
});

it("offers 'Fäll ihop' also when the strip cannot work (no tool proxy, no messages)", () => {
  setup({ onCollapse: vi.fn(), features: NOTHING });
  expect(screen.queryByRole("navigation")).toBeNull();
  expect(screen.getByRole("button", { name: "Fäll ihop" })).toBeInTheDocument();
});

it("offers no 'Tillbaka' in Control when the strip could not work", () => {
  setup({ features: NOTHING }, { room: "control", view: "trash" });
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
});

it("draws only the rooms a host names in stripRooms, and the keys move between those", () => {
  setup({ stripRooms: ["work", "journal", "shopping"] });
  const nav = screen.getByRole("navigation", { name: "Rum" });
  expect(
    Array.from(nav.querySelectorAll("button")).map((b) => b.textContent),
  ).toEqual(["Arbete", "Dagbok", "Inköp"]);
  expect(tab("Dagbok")).toHaveAttribute("aria-current", "page");
  tab("Dagbok").focus();
  fireEvent.keyDown(tab("Dagbok"), { key: "ArrowRight" });
  expect(tab("Inköp")).toHaveFocus();
});

it("keeps one tab stop on the first listed room when the active room is not in stripRooms", () => {
  setup({ stripRooms: ["work", "shopping"] });
  // The journal is shown (the start room) but is not in the strip: no tab is current, the first one is the tab stop.
  const nav = screen.getByRole("navigation", { name: "Rum" });
  const tabs = Array.from(nav.querySelectorAll("button"));
  expect(tabs.filter((b) => b.hasAttribute("aria-current"))).toHaveLength(0);
  expect(tab("Arbete")).toHaveAttribute("tabindex", "0");
  expect(tab("Inköp")).toHaveAttribute("tabindex", "-1");
});

it("the narrow room picker lists the same rooms as stripRooms", () => {
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
  setup({ stripRooms: ["work", "journal", "shopping"] });
  fireEvent.click(
    document.querySelector<HTMLButtonElement>(".sk-rooms .sk-pick")!,
  );
  expect(
    screen.getAllByRole("menuitemradio").map((item) => item.textContent),
  ).toEqual(["Arbete", "Dagbok", "Inköp"]);
  vi.restoreAllMocks();
});

it("gives way to the room picker when the four rooms do not fit, and a choice switches the room without a model turn", () => {
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
  const { onSendMessage } = setup();
  const pick = document.querySelector<HTMLButtonElement>(".sk-rooms .sk-pick")!;
  expect(pick).toHaveTextContent("Dagbok");
  expect(pick).toHaveAttribute("aria-haspopup", "menu");
  fireEvent.click(pick);
  const items = screen.getAllByRole("menuitemradio");
  expect(items.map((item) => item.textContent)).toEqual([
    "Arbete",
    "Dagbok",
    "Kontakter",
    "Inköp",
  ]);
  expect(items[1]).toHaveAttribute("aria-checked", "true");
  fireEvent.click(items[2]!);
  expect(screen.queryByRole("menu")).toBeNull();
  expect(pane("contacts")).not.toHaveAttribute("hidden");
  expect(pick).toHaveTextContent("Kontakter");
  expect(onSendMessage).not.toHaveBeenCalled();
  vi.restoreAllMocks();
});

it("in Kontroll the room picker says Rum and marks no room, and its first room takes the focus when it opens", () => {
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
  setup({}, { room: "control", view: "trash" });
  // Kontroll applies to every room, so no room is the chosen one; the button says "Rum".
  const pick = document.querySelector<HTMLButtonElement>(".sk-rooms .sk-pick")!;
  expect(pick).toHaveTextContent("Rum");
  fireEvent.click(pick);
  const items = screen.getAllByRole("menuitemradio");
  expect(items.map((item) => item.textContent)).toEqual([
    "Arbete",
    "Dagbok",
    "Kontakter",
    "Inköp",
  ]);
  for (const item of items)
    expect(item).not.toHaveAttribute("aria-checked", "true");
  expect(items[0]).toHaveFocus();
  vi.restoreAllMocks();
});

it("moves focus into the new room's heading after a room change", () => {
  setup();
  fireEvent.click(tab("Arbete"));
  expect(screen.getByRole("heading", { name: "work/root/-" })).toHaveFocus();
});

it("moves between strip buttons with the arrow keys", () => {
  setup();
  tab("Dagbok").focus();
  fireEvent.keyDown(tab("Dagbok"), { key: "ArrowRight" });
  expect(tab("Kontakter")).toHaveFocus();
  fireEvent.keyDown(tab("Kontakter"), { key: "End" });
  expect(tab("Inköp")).toHaveFocus();
  fireEvent.keyDown(tab("Inköp"), { key: "Home" });
  expect(tab("Arbete")).toHaveFocus();
});

it("keeps unsaved form text when only the language changes", () => {
  const FormStub = (props: ShellRoomProps) => (
    <input aria-label="draft" data-room-input={props.entry.room} />
  );
  const formRooms = Object.fromEntries(
    ROOM_IDS.map((room) => [room, FormStub]),
  ) as RoomRegistry;
  const { rerender } = setup({ rooms: formRooms });
  const field = screen.getAllByLabelText("draft")[0] as HTMLInputElement;
  fireEvent.change(field, { target: { value: "half-written note" } });
  expect(tab("Dagbok")).toBeInTheDocument();

  rerender(
    <SidekickShell
      locale="en"
      rooms={formRooms}
      start={journalStart}
      full
      features={LOCAL}
    />,
  );

  expect(tab("Journal")).toBeInTheDocument();
  expect((screen.getAllByLabelText("draft")[0] as HTMLInputElement).value).toBe(
    "half-written note",
  );
});
