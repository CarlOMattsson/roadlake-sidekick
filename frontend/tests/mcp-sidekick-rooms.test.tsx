import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  STALE_AFTER_MS,
} from "@/features/mcp-apps/sidekick-shell";
import {
  SIDEKICK_ROOMS,
  RoomHostContext,
  entryOfTarget,
  initialFor,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import { dirtyDomains } from "@/features/mcp-apps/dirty-domains";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { useShortcuts } from "@/features/mcp-apps/ui/shortcuts";

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

const calls: string[] = [];
const call = vi.fn(async (name: string, args: object) => {
  await Promise.resolve();
  calls.push(name);
  void args;
  switch (name) {
    case "get_work_agenda":
      return { items: [], filters: {}, next_cursor: null };
    case "list_tasks":
      return { items: [], next_cursor: null };
    case "list_contacts":
      return { contacts: [], next_cursor: null };
    case "get_contact_context":
      throw new Error("forbidden");
    default:
      throw new Error(`unexpected ${name}`);
  }
});
const host: RoomHost = {
  transport: {
    call: call as unknown as RoomHost["transport"]["call"],
    requestDisplayMode: vi.fn().mockResolvedValue("inline"),
    updateModelContext: vi.fn().mockResolvedValue(undefined),
  },
  fullscreenAvailable: () => false,
  onExpand: vi.fn(),
};

const start: NavEntry = { room: "contacts", view: "list" };

function setup(over: Partial<Parameters<typeof SidekickShell>[0]> = {}) {
  return render(
    <RoomHostContext.Provider value={host}>
      <SidekickShell
        locale="en"
        rooms={SIDEKICK_ROOMS}
        start={start}
        full
        features={LOCAL}
        {...over}
      />
    </RoomHostContext.Provider>,
  );
}

beforeEach(() => {
  calls.length = 0;
  call.mockClear();
});
afterEach(() => {
  cleanup();
  vi.useRealTimers();
});

it("reads the contact list for itself when the Contacts room opens without a result", async () => {
  setup();
  await waitFor(() => expect(calls).toContain("list_contacts"));
});

it("mounts the Work room hidden on first visit, reads its agenda, and reads it again after a long absence", async () => {
  vi.useFakeTimers({ toFake: ["Date"] });
  setup();
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  await waitFor(() => expect(calls).toContain("get_work_agenda"));
  const reads = () => calls.filter((name) => name === "get_work_agenda").length;
  expect(reads()).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
  // Back within a minute: the room stays as it was.
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  expect(reads()).toBe(1);
  fireEvent.click(screen.getByRole("button", { name: "Contacts" }));
  act(() => {
    vi.setSystemTime(Date.now() + STALE_AFTER_MS + 1000);
  });
  fireEvent.click(screen.getByRole("button", { name: "Work" }));
  await waitFor(() => expect(reads()).toBe(2));
});

it("draws no second frame around a room in the full view", () => {
  const { container } = setup();
  expect(container.querySelectorAll(".sk-frame")).toHaveLength(1);
});

it("keeps shortcuts of a hidden room off", () => {
  const action = vi.fn();
  function Probe() {
    useShortcuts({ x: action });
    return null;
  }
  function Harness() {
    const [active, setActive] = useState(false);
    return (
      <RoomSurfaceContext.Provider value={{ active, framed: true }}>
        <button onClick={() => setActive(true)}>show</button>
        <Probe />
      </RoomSurfaceContext.Provider>
    );
  }
  render(<Harness />);
  fireEvent.keyDown(window, { key: "x" });
  expect(action).not.toHaveBeenCalled();
  fireEvent.click(screen.getByText("show"));
  fireEvent.keyDown(window, { key: "x" });
  expect(action).toHaveBeenCalledTimes(1);
});

it("gives a cross-link an id-only result and drops a stale result after a refresh", () => {
  const contact: NavEntry = { room: "contacts", view: "contact", id: "c1" };
  expect(initialFor(contact, true, false)).toMatchObject({
    contact: { id: "c1" },
  });
  expect(
    initialFor({ room: "work", view: "task", id: "t1" }, true, false),
  ).toEqual({
    task: { id: "t1" },
  });
  const agenda: NavEntry = {
    room: "work",
    view: "agenda",
    data: { items: [] },
  };
  expect(initialFor(agenda, true, false)).toBe(agenda.data);
  // A card's own entry has no id; the record id in its result is enough for the inline re-read.
  expect(
    initialFor(
      { room: "work", view: "task", data: { task: { id: "t9", title: "x" } } },
      false,
      true,
    ),
  ).toEqual({ task: { id: "t9" } });
  // A list has no id to read by: a refreshed inline card keeps what it has.
  expect(initialFor(agenda, true, true)).toBe(agenda.data);
  expect(
    initialFor(
      { room: "work", view: "task", id: "t1", data: { task: { id: "t1" } } },
      false,
      true,
    ),
  ).toEqual({ task: { id: "t1" } });
  // In the full view a journal card opens the entry view itself.
  const card: NavEntry = {
    room: "journal",
    view: "card",
    data: { entry: { id: "e1", title: "T" } },
  };
  expect(initialFor(card, false, false)).toBe(card.data);
  expect(initialFor(card, true, false)).toEqual({ entry: { id: "e1" } });
  expect(entryOfTarget({ room: "work" })).toMatchObject({ view: "root" });
});

// An inline Contact list has no id to read by: a refreshed card reads the list for itself, unless it
// answered a search (the room cannot read a search for itself yet, so the card keeps its result).
it("reads an inline Contact list again after a write in the full view, but keeps a searched one", async () => {
  const list = (q: string): NavEntry => ({
    room: "contacts",
    view: "list",
    data: {
      contacts: [{ id: "c1", display_name: "Anna Andersson" }],
      q,
      include_archived: false,
      next_cursor: null,
    },
  });
  const Card = SIDEKICK_ROOMS.contacts;
  const shell = (entry: NavEntry, refreshKey: number) => ({
    entry,
    full: false,
    visible: true,
    refreshKey,
    markDirty: () => undefined,
    locale: "en" as const,
  });
  const whole = render(
    <RoomHostContext.Provider value={host}>
      <Card {...shell(list(""), 1)} />
    </RoomHostContext.Provider>,
  );
  await waitFor(() => expect(calls).toContain("list_contacts"));
  whole.unmount();

  calls.length = 0;
  render(
    <RoomHostContext.Provider value={host}>
      <Card {...shell(list("Anna"), 1)} />
    </RoomHostContext.Provider>,
  );
  await act(() => Promise.resolve());
  expect(calls).not.toContain("list_contacts");
});

it("marks the domains a write may have changed and none for a read", () => {
  expect(dirtyDomains("get_task")).toEqual([]);
  expect(dirtyDomains("list_contacts")).toEqual([]);
  expect(dirtyDomains("complete_task")).toEqual([
    "work",
    "contacts",
    "control",
  ]);
  expect(dirtyDomains("set_shopping_item_purchased")).toEqual([
    "shopping",
    "control",
  ]);
  expect(dirtyDomains("finalize_journal_draft")).toEqual([
    "journal",
    "work",
    "contacts",
    "control",
  ]);
  expect(dirtyDomains("link_contact_to_task")).toEqual([
    "contacts",
    "work",
    "journal",
    "control",
  ]);
  expect(dirtyDomains("restore_from_trash")).toHaveLength(5);
});

// Ändringar, Papperskorg, Aktivitet and Minne in Kontroll show what every write changes.
it("marks Kontroll with every write, also a memory setting, and never with a read", () => {
  expect(dirtyDomains("set_memory_settings")).toEqual(["control"]);
  for (const tool of [
    "complete_task",
    "update_contact",
    "add_shopping_items",
    "write_journal_entry",
    "move_to_trash",
  ])
    expect(dirtyDomains(tool)).toContain("control");
  for (const tool of ["get_task", "list_trash", "show_work_changes"])
    expect(dirtyDomains(tool)).not.toContain("control");
});
