import type { ComponentType, MutableRefObject, ReactNode } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type {
  ListLayout,
  NavEntry,
  NavState,
  Split,
} from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import {
  UnsavedGuardContext,
  type UnsavedRegistry,
} from "@/features/mcp-apps/unsaved-guard";
import { RenderErrorBoundary } from "@/features/mcp-apps/ui/error-boundary";
import {
  RoomSurfaceContext,
  type RoomSurface,
} from "@/features/mcp-apps/ui/room-context";
import {
  DetailHints,
  PaneHead,
  recordKey,
  SplitLayout,
} from "@/features/mcp-apps/ui/split-layout";
import { layersOf } from "./shell-layers";
import type { ShellRoomProps } from "./shell-types";

/** What the active room's split pane needs from the shell (sidekick-shell.tsx): its head's texts and actions. */
export type ShellSplit = {
  /** The split of each room (nav-state splitOf); a room that is not here is drawn alone. */
  of: Partial<Record<RoomId, Split>>;
  /** The record beside the list was just swapped for the next one: it does not slide in. */
  swapped: boolean;
  /** The detail pane's head: the "‹ parent" of a stack of its own, the kind's name and the ×. */
  backLabel: string;
  onBack: () => void;
  onClose: () => void;
  /** Where the detail's own pen and ⋯ go (BackHeaderActions), and where a room's SplitAside goes. */
  paneSlot: HTMLSpanElement | null;
  setPaneSlot: (element: HTMLSpanElement | null) => void;
  asideSlot: HTMLElement | null;
  setAsideSlot: (element: HTMLElement | null) => void;
  /** A list said what it is now (useListLayout). */
  setLayout: (layerId: string, layout: ListLayout) => void;
  /** The keys the hints list; absent where single keys are off. */
  hintKeys?: { label: string; entries: { keys: string; label: string }[] };
};

/** The role of layer `index` in a pane split as `split`, or undefined for a layer that is not drawn. */
function paneOf(
  split: Split,
  index: number,
  top: boolean,
): RoomSurface["pane"] | undefined {
  switch (split.kind) {
    case "single":
      return top ? "single" : undefined;
    case "aside":
      return index === split.list ? "list" : undefined;
    case "split":
    case "drawer":
      if (index === split.list) return "list";
      if (index === split.detail)
        return split.kind === "split" ? "detail" : "drawer";
      return undefined;
  }
}

/**
 * Every room the user has visited, mounted: the root and each cross-link above it stay in place and only the
 * top layer of the active room is shown. Back then returns to exactly the state the layer below was left in
 * (an open draft, a basket). In a wide frame the active room's pane may be split (nav-state splitOf): the list a
 * record was opened from stays shown beside it, or under it as a drawer. The layers keep their places as siblings
 * in every form, so a split that comes or goes never mounts a room again.
 */
export function ShellPanes({
  nav,
  rooms,
  labels,
  locale,
  paneEls,
  roomProps,
  setUnsaved,
  strip,
  backSlot,
  headSlot,
  split,
}: {
  nav: NavState;
  rooms: Record<RoomId, ComponentType<ShellRoomProps>>;
  labels: SidekickShellLabels;
  locale: AppLocale;
  paneEls: MutableRefObject<Partial<Record<RoomId, HTMLElement | null>>>;
  roomProps: (
    room: RoomId,
    layer: NavEntry,
    layerId: string,
    shown: boolean,
  ) => ShellRoomProps;
  /** Where a layer reports its unsaved edits (useUnsavedGuard). */
  setUnsaved: UnsavedRegistry["set"];
  /** Whether the strip names the room above the panes. */
  strip: boolean;
  /** Where the layer on top puts its own pen and ⋯ in the Back row; null when there is no Back row. */
  backSlot: HTMLSpanElement | null;
  /** Where the layer on top draws its room head in a wide frame (the bar's row); null when it draws it in place. */
  headSlot: HTMLDivElement | null;
  split: ShellSplit;
}): ReactNode {
  return nav.visited.map((room) => {
    const layers = layersOf(nav, room);
    const active = room === nav.active;
    const roomSplit: Split = (active && split.of[room]) || { kind: "single" };
    // The record the detail's stack started from: its row in the list is the chosen one, also while the detail shows
    // a record opened from it (a Task of the Contact).
    const opened =
      roomSplit.kind === "split" || roomSplit.kind === "drawer"
        ? layers[roomSplit.list + 1]?.entry
        : undefined;
    const beside =
      opened?.id !== undefined
        ? recordKey({ room: opened.room, view: opened.view, id: opened.id })
        : undefined;
    // The detail holds a stack of its own (a Contact opened from its Task): its head leads back one step.
    const ownStack =
      (roomSplit.kind === "split" || roomSplit.kind === "drawer") &&
      roomSplit.detail - roomSplit.list > 1;
    // The empty detail beside a list names what the list holds: by its view first (Start's automations), then its room.
    const asideList =
      roomSplit.kind === "aside" ? layers[roomSplit.list]?.entry : undefined;
    const pick =
      (asideList && labels.split.pick[`${asideList.room}:${asideList.view}`]) ??
      labels.split.pick[room] ??
      labels.split.pickOther;
    return (
      <section
        key={room}
        ref={(element) => {
          paneEls.current[room] = element;
        }}
        className="sk-rooms__pane"
        data-room={room}
        aria-label={labels.rooms[room]}
        tabIndex={-1}
        hidden={!active}
      >
        <SplitLayout
          split={roomSplit.kind}
          swapped={split.swapped}
          shown={
            roomSplit.kind === "split" || roomSplit.kind === "drawer"
              ? layers[roomSplit.detail]?.id
              : undefined
          }
        >
          {layers.map((layer, index) => {
            const Room = rooms[layer.entry.room];
            const pane = paneOf(roomSplit, index, layer.top);
            const shown = active && pane !== undefined;
            const isDetail = pane === "detail" || pane === "drawer";
            const isList = pane === "list";
            // The bar's head belongs to the list in a split, to the layer on top otherwise.
            const holdsHead = roomSplit.kind === "single" ? layer.top : isList;
            const viewKey = `${layer.entry.room}:${layer.entry.view}`;
            return (
              <div
                key={layer.id}
                className="sk-rooms__layer"
                data-layer-top={layer.top ? "true" : undefined}
                data-pane={pane === "single" ? undefined : pane}
                hidden={pane === undefined}
              >
                {isDetail ? (
                  <PaneHead
                    kind={
                      labels.split.kinds[viewKey] ??
                      labels.rooms[layer.entry.room]
                    }
                    back={
                      ownStack
                        ? { label: split.backLabel, onBack: split.onBack }
                        : undefined
                    }
                    close={{
                      label:
                        labels.split.close[viewKey] ?? labels.split.closeOther,
                      onClose: split.onClose,
                    }}
                    slotRef={split.setPaneSlot}
                  />
                ) : null}
                <UnsavedGuardContext.Provider
                  value={{ layer: layer.id, set: setUnsaved }}
                >
                  <RoomSurfaceContext.Provider
                    value={{
                      active: shown,
                      framed: true,
                      room: layer.entry.room,
                      view: layer.entry.view,
                      // The host asked for no strip (the phone's single room), so nothing above names the room: the
                      // room's own header row does. A host that merely cannot navigate keeps today's frame.
                      heading: strip
                        ? undefined
                        : labels.rooms[layer.entry.room],
                      backActions: isDetail
                        ? split.paneSlot
                        : backSlot && active && layer.top
                          ? backSlot
                          : null,
                      headSlot:
                        headSlot && active && holdsHead ? headSlot : null,
                      pane,
                      beside: isList ? beside : undefined,
                      asideSlot:
                        isList && roomSplit.kind === "aside"
                          ? split.asideSlot
                          : null,
                      setLayout: (layout) => split.setLayout(layer.id, layout),
                    }}
                  >
                    <RenderErrorBoundary
                      locale={locale}
                      scope={layer.entry.room}
                    >
                      <Room
                        {...roomProps(room, layer.entry, layer.id, shown)}
                      />
                    </RenderErrorBoundary>
                  </RoomSurfaceContext.Provider>
                </UnsavedGuardContext.Provider>
              </div>
            );
          })}
          {roomSplit.kind === "aside" ? (
            <aside
              key="aside"
              ref={split.setAsideSlot}
              className="sk-split__aside"
              aria-label={pick}
            >
              <DetailHints sentence={pick} keys={split.hintKeys} />
            </aside>
          ) : null}
        </SplitLayout>
      </section>
    );
  });
}
