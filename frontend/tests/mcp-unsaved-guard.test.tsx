import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import {
  createUnsavedRegistry,
  useUnsavedGuard,
} from "@/features/mcp-apps/unsaved-guard";
import { ROOM_IDS } from "@/features/mcp-apps/router";
import { EntryTextForm } from "@/features/journal-app/entry-write";
import { journalEn } from "@/features/journal-app/labels";
import { TaskEditor } from "@/features/work-app/task-edit";
import { workEn } from "@/features/work-app/labels";
import { taskA } from "./helpers/work-app-fixtures";

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};

afterEach(cleanup);

function Plain() {
  const [text, setText] = useState("");
  useUnsavedGuard(text !== "");
  return (
    <input
      aria-label="plain"
      value={text}
      onChange={(event) => setText(event.target.value)}
    />
  );
}

/**
 * A room whose root has a button that pushes one layer, and whose pushed layer shows `form`. Every room
 * is this stub, so the pushed layer can be a cross-link into any of them.
 */
function roomsWith(form: (props: ShellRoomProps) => React.ReactNode) {
  function Stub(props: ShellRoomProps) {
    if (props.entry.id) return <div>{form(props)}</div>;
    return (
      <div>
        <h2>root</h2>
        <button
          type="button"
          onClick={() =>
            props.navigate?.({ room: "work", view: "task", id: "t1" })
          }
        >
          open
        </button>
      </div>
    );
  }
  return Object.fromEntries(
    ROOM_IDS.map((room) => [room, Stub]),
  ) as RoomRegistry;
}

function mountShell(
  rooms: RoomRegistry,
  over: Partial<Parameters<typeof SidekickShell>[0]> = {},
) {
  return render(
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={{ room: "work", view: "board" }}
      full
      features={LOCAL}
      {...over}
    />,
  );
}

function openLayer() {
  fireEvent.click(screen.getByRole("button", { name: "open" }));
}
const backRow = () =>
  screen.getByRole("button", { name: /^Tillbaka till|^Back to/ });

it("registry: a layer is dirty while a form in it reports unsaved edits", () => {
  const registry = createUnsavedRegistry();
  expect(registry.isDirty(["a", "b"])).toBe(false);
  registry.set("a", "f1", true);
  registry.set("a", "f2", true);
  expect(registry.isDirty(["b"])).toBe(false);
  expect(registry.isDirty(["a"])).toBe(true);
  registry.set("a", "f1", false);
  expect(registry.isDirty(["a"])).toBe(true);
  registry.set("a", "f2", false);
  expect(registry.isDirty(["a"])).toBe(false);
});

it("the hook does nothing outside the shell", () => {
  render(<Plain />);
  fireEvent.input(screen.getByLabelText("plain"), { target: { value: "x" } });
  expect(screen.getByLabelText("plain")).toHaveValue("x");
});

it("Back with no unsaved edits goes back at once, without a question", () => {
  mountShell(roomsWith(() => <Plain />));
  openLayer();
  fireEvent.click(backRow());
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("Back with unsaved edits asks first: Fortsätt redigera stays, Släng goes back", () => {
  mountShell(roomsWith(() => <Plain />));
  openLayer();
  fireEvent.input(screen.getByLabelText("plain"), {
    target: { value: "halvskrivet" },
  });
  fireEvent.click(backRow());

  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  const keep = screen.getByRole("button", { name: "Fortsätt redigera" });
  expect(keep).toHaveFocus();
  fireEvent.click(keep);
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.getByLabelText("plain")).toHaveValue("halvskrivet");

  fireEvent.click(backRow());
  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
});

it("asks in English for an English app", () => {
  mountShell(
    roomsWith(() => <Plain />),
    { locale: "en" },
  );
  openLayer();
  fireEvent.input(screen.getByLabelText("plain"), { target: { value: "x" } });
  fireEvent.click(backRow());
  expect(screen.getByText("Discard your changes?")).toBeInTheDocument();
  expect(screen.getByRole("button", { name: "Discard" })).toBeInTheDocument();
  expect(
    screen.getByRole("button", { name: "Keep editing" }),
  ).toBeInTheDocument();
});

it("pressing the active room tab goes to the root only after asking", () => {
  mountShell(roomsWith(() => <Plain />));
  openLayer();
  fireEvent.input(screen.getByLabelText("plain"), { target: { value: "x" } });
  fireEvent.click(screen.getByRole("button", { name: "Arbete" }));
  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  expect(screen.getByLabelText("plain")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("system Back (Android) asks too; a second Back answers Fortsätt redigera", () => {
  let systemBack: (() => boolean) | undefined;
  mountShell(
    roomsWith(() => <Plain />),
    {
      registerBack: (handler) => {
        systemBack = handler;
      },
    },
  );
  openLayer();
  // Clean: it goes back one layer.
  act(() => {
    expect(systemBack?.()).toBe(true);
  });
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();

  openLayer();
  fireEvent.input(screen.getByLabelText("plain"), { target: { value: "x" } });
  act(() => {
    expect(systemBack?.()).toBe(true);
  });
  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  act(() => {
    expect(systemBack?.()).toBe(true);
  });
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.getByLabelText("plain")).toBeInTheDocument();

  act(() => {
    systemBack?.();
  });
  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("the Task editor asks only once a field differs from the Task", () => {
  mountShell(
    roomsWith(() => (
      <TaskEditor
        task={taskA}
        busy={false}
        saveFailed={false}
        onSave={vi.fn()}
        onCancel={vi.fn()}
        labels={workEn}
      />
    )),
  );
  openLayer();
  fireEvent.click(backRow());
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();

  openLayer();
  const title = screen.getByLabelText(workEn.titleLabel);
  fireEvent.input(title, { target: { value: "Ring Anna idag" } });
  fireEvent.click(backRow());
  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  // A change reverted by hand is no change.
  fireEvent.click(screen.getByRole("button", { name: "Fortsätt redigera" }));
  fireEvent.input(title, { target: { value: taskA.title } });
  fireEvent.click(backRow());
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("the journal entry form asks once something is written", () => {
  mountShell(
    roomsWith(() => (
      <EntryTextForm
        labels={journalEn}
        kind="append"
        signatureBase="e1:1"
        submit={vi.fn().mockResolvedValue(undefined)}
        onCancel={vi.fn()}
      />
    )),
  );
  openLayer();
  fireEvent.click(backRow());
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();

  openLayer();
  fireEvent.input(screen.getByRole("textbox"), {
    target: { value: "Ett halvskrivet tillägg" },
  });
  fireEvent.click(backRow());
  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.getByRole("heading", { name: "root" })).toBeVisible();
});

it("a new tool result or a record to open at waits while a form holds unsaved edits", () => {
  const rooms = roomsWith(() => <Plain />);
  const view = mountShell(rooms);
  openLayer();
  const input = screen.getByLabelText("plain");
  fireEvent.input(input, { target: { value: "halvskrivet" } });

  const props = (over: Partial<Parameters<typeof SidekickShell>[0]>) => (
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={{ room: "work", view: "board" }}
      full
      features={LOCAL}
      {...over}
    />
  );
  view.rerender(props({ start: { room: "work", view: "board", id: "new" } }));
  view.rerender(
    props({
      start: { room: "work", view: "board", id: "new" },
      openAt: { room: "work", view: "task", id: "t2" },
    }),
  );
  expect(screen.getByLabelText("plain")).toHaveValue("halvskrivet");

  // Once the edits are discarded the waiting result is answered.
  fireEvent.click(backRow());
  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.queryByLabelText("plain")).not.toBeNull();
});
