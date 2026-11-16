import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import {
  SIDEKICK_ROOMS,
  RoomHostContext,
  type RoomHost,
} from "@/features/mcp-apps/sidekick-rooms";
import { workSv } from "@/features/work-app/shared/labels";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";

// The Work room draws in the app language (Swedish by default), so its words come from workSv.
// The shell gives a room on a layer its own Back (the Back row's step), and a Task marked done leaves with it. These
// are simulated-host tests (a fake host transport), not tests in a real Claude or Android host.

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

/* A stub for every room: records what the shell gave it. */

let seen: Partial<Record<RoomId, ShellRoomProps>>;

function record(props: ShellRoomProps) {
  seen[props.entry.room] = props;
}
function Stub(props: ShellRoomProps) {
  record(props);
  return <h2>{`${props.entry.room}/${props.entry.view}`}</h2>;
}
const stubs = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;

const journalStart: NavEntry = {
  room: "journal",
  view: "day",
  id: "2026-11-03",
};

beforeEach(() => {
  seen = {};
});
afterEach(() => {
  cleanup();
});

it("gives a room Back only when there is a layer to go back from, and Back pops that layer", () => {
  render(
    <SidekickShell
      locale="en"
      rooms={stubs}
      start={journalStart}
      full
      features={LOCAL}
    />,
  );
  // The root of the stack has nowhere to go back to.
  expect(seen.journal?.back).toBeUndefined();

  act(() =>
    seen.journal?.navigate?.({ room: "contacts", view: "contact", id: "c1" }),
  );
  const back = seen.contacts?.back;
  expect(back).toBeTypeOf("function");
  expect(
    screen.getByRole("heading", { name: "contacts/contact" }),
  ).toBeVisible();

  act(() => back?.());
  expect(screen.queryByRole("button", { name: /^Tillbaka/ })).toBeNull();
  expect(seen.journal?.back).toBeUndefined();
  expect(screen.getByRole("heading", { name: "journal/day" })).toBeVisible();
});

it("gives no Back to a room drawn inline in a card", () => {
  render(
    <SidekickShell
      locale="en"
      rooms={stubs}
      start={journalStart}
      full={false}
      features={LOCAL}
    />,
  );
  expect(seen.journal?.back).toBeUndefined();
});

/* The real Work room on a layer, with a fake host answering its tools. */

const task = {
  id: "019f0000-0000-7000-8000-0000000000a1",
  title: "Ring Anna om offerten",
  status: "todo",
  due_at: null,
  version: 1,
};
const agendaItem = { kind: "task", ...task, agenda_group: "undated" };

const calls: { name: string; args: unknown }[] = [];
// The server's copy of the Task: update_task changes it, and a later agenda read shows it as it now is.
let stored = { ...task };
const call = vi.fn(async (name: string, args: unknown) => {
  await Promise.resolve();
  calls.push({ name, args });
  switch (name) {
    case "get_task":
      return { task: stored };
    case "update_task":
      stored = {
        ...stored,
        ...(args as { changes?: object }).changes,
        status: "completed",
        version: 2,
      };
      return { task: stored };
    case "get_work_agenda":
      return {
        items: [{ ...agendaItem, ...stored }],
        filters: {},
        next_cursor: null,
      };
    case "list_task_contacts":
    case "list_task_steps":
    case "list_task_external_references":
      return { items: [], filters: {}, next_cursor: null };
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

it("returns a Task opened from the agenda to the agenda when it is marked done", async () => {
  calls.length = 0;
  stored = { ...task };
  const start: NavEntry = {
    room: "work",
    view: "agenda",
    data: { items: [agendaItem], filters: {}, next_cursor: null },
  };
  render(
    <RoomHostContext.Provider value={host}>
      <SidekickShell
        locale="en"
        rooms={SIDEKICK_ROOMS}
        start={start}
        full
        features={LOCAL}
      />
    </RoomHostContext.Provider>,
  );
  fireEvent.click(await screen.findByRole("button", { name: task.title }));
  // The Task is a layer of the shell: its Back row names the agenda it was opened from.
  expect(
    await screen.findByRole("button", { name: /^Tillbaka till Agenda/ }),
  ).toBeVisible();
  fireEvent.click(await screen.findByRole("button", { name: workSv.markDone }));

  await waitFor(() =>
    expect(calls.some(({ name }) => name === "update_task")).toBe(true),
  );
  // The layer is left by the shell's Back: the Back row is gone and the agenda shows the Task again.
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: /^Tillbaka till / }),
    ).toBeNull(),
  );
  expect(screen.queryByRole("button", { name: workSv.markDone })).toBeNull();
  // The agenda reads again after the write (when that answer lands depends on the renderer's effect timing), and
  // shows the Task as the server now has it.
  const written = calls.findIndex(({ name }) => name === "update_task");
  await waitFor(() =>
    expect(
      calls.slice(written).some(({ name }) => name === "get_work_agenda"),
    ).toBe(true),
  );
  expect(await screen.findByRole("button", { name: task.title })).toBeVisible();
});
