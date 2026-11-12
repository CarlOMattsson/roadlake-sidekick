import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
} from "@testing-library/react";
import { useRef, useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";

import type { HostFeatures } from "@/features/mcp-apps/bridge";
import { ROOM_IDS } from "@/features/mcp-apps/router";
import {
  SidekickShell,
  type RoomRegistry,
  type ShellRoomProps,
} from "@/features/mcp-apps/sidekick-shell";
import { useUnsavedGuard } from "@/features/mcp-apps/unsaved-guard";

// Capacitor's App plugin, as in mobile-platform-native.test.ts: the hardware Back button reaches the registered handler.
type Listener = (event: unknown) => void;
const listeners = new Map<string, Listener>();
const exitApp = vi.fn(() => Promise.resolve());

vi.mock("@capacitor/app", () => ({
  App: {
    getLaunchUrl: () => Promise.resolve(undefined),
    exitApp: () => exitApp(),
    addListener: vi.fn((name: string, listener: Listener) => {
      listeners.set(name, listener);
      return Promise.resolve({ remove: () => listeners.delete(name) });
    }),
  },
}));

const { createNativePlatform } = await import("@/mobile/platform-native");

const LOCAL: HostFeatures = {
  serverTools: true,
  message: true,
  openLinks: true,
};
const pressAndroidBack = () =>
  listeners.get("backButton")?.({ canGoBack: false });

beforeEach(() => {
  listeners.clear();
  exitApp.mockClear();
});
afterEach(cleanup);

function Form() {
  const [text, setText] = useState("");
  useUnsavedGuard(text !== "");
  return (
    <input
      aria-label="note"
      value={text}
      onChange={(event) => setText(event.target.value)}
    />
  );
}

function Stub(props: ShellRoomProps) {
  if (props.entry.id) return <Form />;
  return (
    <button
      type="button"
      onClick={() => props.navigate?.({ room: "work", view: "task", id: "t1" })}
    >
      open
    </button>
  );
}
const rooms = Object.fromEntries(
  ROOM_IDS.map((room) => [room, Stub]),
) as RoomRegistry;

/** The shell wired to the Android platform the way mobile-app.tsx does it. */
function Android({
  onBack,
}: {
  onBack: (handler: () => boolean) => () => void;
}) {
  const off = useRef<(() => void) | undefined>(undefined);
  return (
    <SidekickShell
      locale="sv"
      rooms={rooms}
      start={{ room: "work", view: "board" }}
      full
      features={LOCAL}
      registerBack={(handler) => {
        off.current?.();
        off.current = handler ? onBack(handler) : undefined;
      }}
    />
  );
}

it("Android Back asks before it drops unsaved edits and does not leave the app", async () => {
  const platform = await createNativePlatform();
  render(<Android onBack={(handler) => platform.onBack(handler)} />);
  fireEvent.click(screen.getByRole("button", { name: "open" }));
  fireEvent.change(screen.getByLabelText("note"), {
    target: { value: "halvskrivet" },
  });

  act(() => {
    pressAndroidBack();
  });
  expect(screen.getByText("Släng ändringarna?")).toBeInTheDocument();
  expect(screen.getByLabelText("note")).toHaveValue("halvskrivet");
  expect(exitApp).not.toHaveBeenCalled();

  fireEvent.click(screen.getByRole("button", { name: "Släng" }));
  expect(screen.getByRole("button", { name: "open" })).toBeVisible();
  expect(exitApp).not.toHaveBeenCalled();
});

it("Android Back without edits goes back at once, and leaves the app at the root", async () => {
  const platform = await createNativePlatform();
  render(<Android onBack={(handler) => platform.onBack(handler)} />);
  fireEvent.click(screen.getByRole("button", { name: "open" }));

  act(() => {
    pressAndroidBack();
  });
  expect(screen.queryByText("Släng ändringarna?")).toBeNull();
  expect(screen.getByRole("button", { name: "open" })).toBeVisible();

  act(() => {
    pressAndroidBack();
  });
  expect(exitApp).toHaveBeenCalledTimes(1);
});
