import { act, renderHook } from "@testing-library/react";
import type { ReactNode } from "react";
import { describe, expect, it, vi } from "vitest";

import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import {
  ShortcutRegistryContext,
  createShortcutRegistry,
  shortcutKeyParts,
  useCharKeys,
  useRoomShortcuts,
  useShortcutGroups,
  type ShortcutHelpGroup,
  type ShortcutRegistry,
} from "@/features/mcp-apps/ui/shortcut-registry";

const group = (id: string, label = "Do it"): ShortcutHelpGroup => ({
  id,
  title: id.toUpperCase(),
  entries: [{ keys: ["j"], label }],
});

describe("createShortcutRegistry", () => {
  it("lists groups in registration order and keeps the place of a replaced group", () => {
    const registry = createShortcutRegistry();
    registry.set("a", group("a"));
    registry.set("b", group("b"));
    registry.set("a", group("a", "Changed"));

    expect(registry.groups().map((g) => g.id)).toEqual(["a", "b"]);
    expect(registry.groups()[0]?.entries[0]?.label).toBe("Changed");

    registry.set("a", undefined);
    expect(registry.groups().map((g) => g.id)).toEqual(["b"]);
  });

  it("returns the same snapshot until something changes and notifies subscribers", () => {
    const registry = createShortcutRegistry();
    const listener = vi.fn();
    const off = registry.subscribe(listener);
    const before = registry.groups();

    registry.set("a", group("a"));
    expect(listener).toHaveBeenCalledTimes(1);
    const after = registry.groups();
    expect(after).not.toBe(before);
    expect(registry.groups()).toBe(after);

    registry.set("missing", undefined);
    expect(listener).toHaveBeenCalledTimes(1);

    off();
    registry.set("b", group("b"));
    expect(listener).toHaveBeenCalledTimes(1);
  });

  it("tells subscribers when single-character shortcuts are switched", () => {
    const registry = createShortcutRegistry();
    const listener = vi.fn();
    registry.subscribe(listener);

    expect(registry.charKeys()).toBe(true);
    registry.setCharKeys(false);
    registry.setCharKeys(false);

    expect(registry.charKeys()).toBe(false);
    expect(listener).toHaveBeenCalledTimes(1);
  });
});

function wrapper(registry: ShortcutRegistry, active = true) {
  return ({ children }: { children: ReactNode }) => (
    <ShortcutRegistryContext.Provider value={registry}>
      <RoomSurfaceContext.Provider value={{ active, framed: false }}>
        {children}
      </RoomSurfaceContext.Provider>
    </ShortcutRegistryContext.Provider>
  );
}

describe("useRoomShortcuts", () => {
  const help = {
    id: "agenda",
    title: "Agenda",
    labels: { j: "Next", ArrowDown: "Next", k: "Previous" },
  };

  it("lists the labelled bindings and merges bindings that share a label", () => {
    const registry = createShortcutRegistry();
    renderHook(
      () =>
        useRoomShortcuts(
          { j: () => {}, ArrowDown: () => {}, k: () => {}, x: () => {} },
          help,
        ),
      { wrapper: wrapper(registry) },
    );

    expect(registry.groups()).toEqual([
      {
        id: "agenda",
        title: "Agenda",
        entries: [
          { keys: ["j", "ArrowDown"], label: "Next" },
          { keys: ["k"], label: "Previous" },
        ],
      },
    ]);
  });

  it("does not re-register when only the identity of the map and labels changes", () => {
    const registry = createShortcutRegistry();
    const listener = vi.fn();
    registry.subscribe(listener);
    const { rerender } = renderHook(
      () =>
        useRoomShortcuts(
          { j: () => {}, k: () => {} },
          { ...help, labels: { ...help.labels } },
        ),
      { wrapper: wrapper(registry) },
    );
    const calls = listener.mock.calls.length;

    rerender();
    rerender();

    expect(listener.mock.calls.length).toBe(calls);
  });

  it("registers only while the layer is active and enabled", () => {
    const registry = createShortcutRegistry();
    renderHook(() => useRoomShortcuts({ j: () => {} }, help), {
      wrapper: wrapper(registry, false),
    });
    expect(registry.groups()).toEqual([]);

    const disabled = createShortcutRegistry();
    renderHook(
      () => useRoomShortcuts({ j: () => {} }, help, { enabled: false }),
      { wrapper: wrapper(disabled) },
    );
    expect(disabled.groups()).toEqual([]);
  });

  it("removes the group on unmount", () => {
    const registry = createShortcutRegistry();
    const { unmount } = renderHook(
      () => useRoomShortcuts({ j: () => {} }, help),
      { wrapper: wrapper(registry) },
    );
    expect(registry.groups()).toHaveLength(1);

    unmount();

    expect(registry.groups()).toEqual([]);
  });
});

describe("registry hooks", () => {
  it("read the groups and the switch, and fall back without a provider", () => {
    const registry = createShortcutRegistry();
    const { result } = renderHook(
      () => ({ groups: useShortcutGroups(), chars: useCharKeys() }),
      { wrapper: wrapper(registry) },
    );
    expect(result.current).toEqual({ groups: [], chars: true });

    act(() => {
      registry.set("a", group("a"));
      registry.setCharKeys(false);
    });
    expect(result.current.groups).toHaveLength(1);
    expect(result.current.chars).toBe(false);

    const bare = renderHook(() => ({
      groups: useShortcutGroups(),
      chars: useCharKeys(),
    }));
    expect(bare.result.current).toEqual({ groups: [], chars: true });
  });
});

describe("shortcutKeyParts", () => {
  it("names keys as they read on a keycap", () => {
    expect(shortcutKeyParts("ArrowDown")).toEqual(["↓"]);
    expect(shortcutKeyParts("ArrowUp")).toEqual(["↑"]);
    expect(shortcutKeyParts("ArrowLeft")).toEqual(["←"]);
    expect(shortcutKeyParts("ArrowRight")).toEqual(["→"]);
    expect(shortcutKeyParts("Escape")).toEqual(["Esc"]);
    expect(shortcutKeyParts("Shift+F10")).toEqual(["Shift", "F10"]);
    expect(shortcutKeyParts("g 1")).toEqual(["g", "1"]);
    expect(shortcutKeyParts("?")).toEqual(["?"]);
  });

  it("writes Mod as Ctrl, or the command key on a Mac", () => {
    expect(shortcutKeyParts("Mod+Enter", false)).toEqual(["Ctrl", "Enter"]);
    expect(shortcutKeyParts("Mod+Enter", true)).toEqual(["⌘", "Enter"]);
  });
});
