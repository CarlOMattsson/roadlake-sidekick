import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import type { ReactElement } from "react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { RoomHead, type RoomHeadProps } from "@/features/mcp-apps/ui/room-head";
import {
  RoomSurfaceContext,
  type RoomSurface,
} from "@/features/mcp-apps/ui/room-context";
import {
  ShortcutRegistryContext,
  createShortcutRegistry,
} from "@/features/mcp-apps/ui/shortcut-registry";

afterEach(cleanup);

const tabs = <div role="group" aria-label="Views" />;
const more = (
  <button type="button" className="sk-iconbtn sk-room-head__tool">
    More
  </button>
);

function head(over: Partial<RoomHeadProps> = {}): ReactElement {
  return (
    <RoomHead
      scope="sidekick-test"
      tabs={tabs}
      keysTitle="Test room"
      more={more}
      search={{ label: "Search", onPress: vi.fn() }}
      add={{ label: "New item", onPress: vi.fn() }}
      {...over}
    />
  );
}

function inContext(
  surface: Partial<RoomSurface>,
  element: ReactElement,
  registry = createShortcutRegistry(),
) {
  return (
    <ShortcutRegistryContext.Provider value={registry}>
      <RoomSurfaceContext.Provider
        value={{ active: true, framed: true, ...surface }}
      >
        {element}
      </RoomSurfaceContext.Provider>
    </ShortcutRegistryContext.Provider>
  );
}

function press(key: string, target: Element | Window = window) {
  fireEvent.keyDown(target, { key });
}

describe("RoomHead cells", () => {
  it("draws the tabs, then search, + and ⋯ in that order, in place", () => {
    const { container } = render(inContext({}, head()));
    const row = container.querySelector<HTMLElement>(".sk-room-head");
    expect(row).not.toBeNull();
    expect(row).toHaveAttribute("data-place", "room");
    const cells = Array.from(row?.children ?? []);
    expect(cells).toHaveLength(4);
    expect(cells[0]).toHaveClass("sk-room-head__tabs");
    expect(cells[0]?.querySelector('[role="group"]')).not.toBeNull();
    expect(cells[1]).toBe(screen.getByRole("button", { name: "Search" }));
    expect(cells[2]).toBe(screen.getByRole("button", { name: "New item" }));
    expect(cells[2]).toHaveClass("sk-iconbtn--primary", "sk-room-head__add");
    expect(cells[3]).toBe(screen.getByRole("button", { name: "More" }));
  });

  it("keeps an empty hidden box where a tool is missing, so the others stay in their cells", () => {
    const { container } = render(
      inContext({}, head({ search: undefined, add: undefined, more: null })),
    );
    const cells = Array.from(
      container.querySelector(".sk-room-head")?.children ?? [],
    );
    expect(cells).toHaveLength(4);
    for (const cell of cells.slice(1)) {
      expect(cell).toHaveClass("sk-room-head__slot");
      expect(cell).toHaveAttribute("aria-hidden", "true");
      expect(cell.textContent).toBe("");
    }
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("puts only the missing tool's box in its own cell", () => {
    const { container } = render(inContext({}, head({ search: undefined })));
    const cells = Array.from(
      container.querySelector(".sk-room-head")?.children ?? [],
    );
    expect(cells[1]).toHaveClass("sk-room-head__slot");
    expect(cells[2]).toBe(screen.getByRole("button", { name: "New item" }));
    expect(cells[3]).toBe(screen.getByRole("button", { name: "More" }));
  });

  it("draws extra between the tabs and the tools", () => {
    const { container } = render(
      inContext({}, head({ extra: <button type="button">Today</button> })),
    );
    const cells = Array.from(
      container.querySelector(".sk-room-head")?.children ?? [],
    );
    expect(cells[1]).toBe(screen.getByRole("button", { name: "Today" }));
    expect(cells[2]).toBe(screen.getByRole("button", { name: "Search" }));
  });

  it("draws only the tabs in place when it has no tools of its own", () => {
    const { container } = render(inContext({}, head({ tools: false })));
    expect(container.querySelector(".sk-room-head")).toBeNull();
    expect(container.querySelector('[role="group"]')).not.toBeNull();
    expect(screen.queryByRole("button")).toBeNull();
  });

  it("keeps the three boxes in the shell's row for a head without tools", () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    render(
      inContext(
        { headSlot: slot },
        head({ tools: false, search: undefined, add: undefined, more: null }),
      ),
    );
    const row = slot.querySelector(".sk-room-head");
    expect(row).not.toBeNull();
    expect(row?.querySelectorAll(".sk-room-head__slot")).toHaveLength(3);
    slot.remove();
  });

  it("names the tools with their key and sets aria-keyshortcuts, and passes the room's class on the row", () => {
    const { container } = render(
      inContext(
        {},
        head({
          className: "sk-shell-tabs",
          search: {
            label: "Search",
            onPress: vi.fn(),
            expanded: true,
            controls: "s1",
          },
        }),
      ),
    );
    const search = screen.getByRole("button", { name: "Search" });
    expect(search).toHaveAttribute("title", "Search (/)");
    expect(search).toHaveAttribute("aria-keyshortcuts", "/");
    expect(search).toHaveAttribute("aria-expanded", "true");
    expect(search).toHaveAttribute("aria-controls", "s1");
    const add = screen.getByRole("button", { name: "New item" });
    expect(add).toHaveAttribute("title", "New item (N)");
    expect(add).toHaveAttribute("aria-keyshortcuts", "n");
    expect(container.querySelector(".sk-room-head")).toHaveClass(
      "sk-room-head",
      "sk-shell-tabs",
    );
  });

  it("presses the tool's handler on a click, and does nothing when disabled", () => {
    const onSearch = vi.fn();
    const onAdd = vi.fn();
    render(
      inContext(
        {},
        head({
          search: { label: "Search", onPress: onSearch },
          add: { label: "New item", onPress: onAdd, disabled: true },
        }),
      ),
    );
    fireEvent.click(screen.getByRole("button", { name: "Search" }));
    expect(onSearch).toHaveBeenCalledTimes(1);
    const add = screen.getByRole("button", { name: "New item" });
    expect(add).toHaveAttribute("aria-disabled", "true");
    fireEvent.click(add);
    expect(onAdd).not.toHaveBeenCalled();
  });
});

describe("RoomHead in the shell's row", () => {
  it("portals the row into the head slot, inside the room's scope, marked as the bar's", () => {
    const slot = document.createElement("div");
    document.body.append(slot);
    const { container } = render(inContext({ headSlot: slot }, head()));
    // Nothing where the room stands; everything in the slot.
    expect(container.querySelector(".sk-room-head")).toBeNull();
    const scope = slot.firstElementChild;
    expect(scope).toHaveClass("sidekick-test", "sk-room-head-scope");
    const row = scope?.querySelector(".sk-room-head");
    expect(row).toHaveAttribute("data-place", "bar");
    expect(row?.querySelector('[role="group"]')).not.toBeNull();
    expect(slot.querySelectorAll("button")).toHaveLength(3);
    slot.remove();
  });
});

describe("RoomHead keys", () => {
  it("presses search on /, with onKey in preference to onPress, and + on n", () => {
    const onPress = vi.fn();
    const onKey = vi.fn();
    const onAdd = vi.fn();
    render(
      inContext(
        {},
        head({
          search: { label: "Search", onPress, onKey },
          add: { label: "New item", onPress: onAdd },
        }),
      ),
    );
    press("/");
    expect(onKey).toHaveBeenCalledTimes(1);
    expect(onPress).not.toHaveBeenCalled();
    press("n");
    expect(onAdd).toHaveBeenCalledTimes(1);
  });

  it("falls back to onPress on / when search has no onKey", () => {
    const onPress = vi.fn();
    render(inContext({}, head({ search: { label: "Search", onPress } })));
    press("/");
    expect(onPress).toHaveBeenCalledTimes(1);
  });

  it("does nothing on a key while the tool is disabled", () => {
    const onSearch = vi.fn();
    const onAdd = vi.fn();
    render(
      inContext(
        {},
        head({
          search: { label: "Search", onPress: onSearch, disabled: true },
          add: { label: "New item", onPress: onAdd, disabled: true },
        }),
      ),
    );
    press("/");
    press("n");
    expect(onSearch).not.toHaveBeenCalled();
    expect(onAdd).not.toHaveBeenCalled();
  });

  it("chooses a view on g and its letter", () => {
    const onAgenda = vi.fn();
    const onStatus = vi.fn();
    render(
      inContext(
        {},
        head({
          views: [
            { key: "a", label: "Agenda", onChoose: onAgenda },
            { key: "s", label: "Status", onChoose: onStatus },
          ],
        }),
      ),
    );
    press("g");
    press("a");
    expect(onAgenda).toHaveBeenCalledTimes(1);
    expect(onStatus).not.toHaveBeenCalled();
    press("g");
    press("s");
    expect(onStatus).toHaveBeenCalledTimes(1);
    // A letter on its own is not a view.
    press("s");
    expect(onStatus).toHaveBeenCalledTimes(1);
  });

  it("ignores the keys typed into a field", () => {
    const onAdd = vi.fn();
    const onSearch = vi.fn();
    render(
      inContext(
        {},
        <>
          {head({
            search: { label: "Search", onPress: onSearch },
            add: { label: "New item", onPress: onAdd },
          })}
          <input aria-label="Field" />
        </>,
      ),
    );
    const field = screen.getByLabelText("Field");
    press("n", field);
    press("/", field);
    expect(onAdd).not.toHaveBeenCalled();
    expect(onSearch).not.toHaveBeenCalled();
  });

  it("is silent on an inactive layer", () => {
    const onAdd = vi.fn();
    const onSearch = vi.fn();
    const onView = vi.fn();
    render(
      inContext(
        { active: false },
        head({
          search: { label: "Search", onPress: onSearch },
          add: { label: "New item", onPress: onAdd },
          views: [{ key: "a", label: "Agenda", onChoose: onView }],
        }),
      ),
    );
    press("n");
    press("/");
    press("g");
    press("a");
    expect(onAdd).not.toHaveBeenCalled();
    expect(onSearch).not.toHaveBeenCalled();
    expect(onView).not.toHaveBeenCalled();
  });

  it("lists its keys in the help under the room's name, only while the layer is active", () => {
    const registry = createShortcutRegistry();
    const views = [{ key: "a", label: "Agenda", onChoose: vi.fn() }];
    const { unmount } = render(inContext({}, head({ views }), registry));
    expect(registry.groups()).toEqual([
      {
        id: "room-head",
        title: "Test room",
        entries: [
          { keys: ["g a"], label: "Agenda" },
          { keys: ["/"], label: "Search" },
          { keys: ["n"], label: "New item" },
        ],
      },
    ]);
    unmount();
    expect(registry.groups()).toEqual([]);

    const hidden = createShortcutRegistry();
    render(inContext({ active: false }, head({ views }), hidden));
    expect(hidden.groups()).toEqual([]);
  });
});
