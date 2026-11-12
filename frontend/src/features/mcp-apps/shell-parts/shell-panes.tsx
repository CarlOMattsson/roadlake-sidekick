import type { ComponentType, MutableRefObject, ReactNode } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { NavEntry, NavState } from "@/features/mcp-apps/nav-state";
import type { RoomId } from "@/features/mcp-apps/router";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import {
  UnsavedGuardContext,
  type UnsavedRegistry,
} from "@/features/mcp-apps/unsaved-guard";
import { RenderErrorBoundary } from "@/features/mcp-apps/ui/error-boundary";
import { RoomSurfaceContext } from "@/features/mcp-apps/ui/room-context";
import { layersOf } from "./shell-layers";
import type { ShellRoomProps } from "./shell-types";

/**
 * Every room the user has visited, mounted: the root and each cross-link above it stay in place and only the
 * top layer of the active room is shown. Back then returns to exactly the state the layer below was left in
 * (an open draft, a basket).
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
}: {
  nav: NavState;
  rooms: Record<RoomId, ComponentType<ShellRoomProps>>;
  labels: SidekickShellLabels;
  locale: AppLocale;
  paneEls: MutableRefObject<Partial<Record<RoomId, HTMLElement | null>>>;
  roomProps: (room: RoomId, layer: NavEntry, layerId: string) => ShellRoomProps;
  /** Where a layer reports its unsaved edits (useUnsavedGuard). */
  setUnsaved: UnsavedRegistry["set"];
  /** Whether the strip names the room above the panes. */
  strip: boolean;
  /** Where the layer on top puts its own pen and ⋯ in the Back row; null when there is no Back row. */
  backSlot: HTMLSpanElement | null;
}): ReactNode {
  return nav.visited.map((room) => {
    const layers = layersOf(nav, room);
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
        hidden={room !== nav.active}
      >
        {layers.map((layer) => {
          const Room = rooms[layer.entry.room];
          return (
            <div
              key={layer.id}
              className="sk-rooms__layer"
              data-layer-top={layer.top ? "true" : undefined}
              hidden={!layer.top}
            >
              <UnsavedGuardContext.Provider
                value={{ layer: layer.id, set: setUnsaved }}
              >
                <RoomSurfaceContext.Provider
                  value={{
                    active: room === nav.active && layer.top,
                    framed: true,
                    room: layer.entry.room,
                    view: layer.entry.view,
                    // The host asked for no strip (the phone's single room), so nothing above names the room: the
                    // room's own header row does. A host that merely cannot navigate keeps today's frame.
                    heading: strip ? undefined : labels.rooms[layer.entry.room],
                    backActions:
                      backSlot && room === nav.active && layer.top
                        ? backSlot
                        : null,
                  }}
                >
                  <RenderErrorBoundary locale={locale} scope={layer.entry.room}>
                    <Room
                      {...roomProps(room, layer.entry, layer.id)}
                      visible={room === nav.active && layer.top}
                    />
                  </RenderErrorBoundary>
                </RoomSurfaceContext.Provider>
              </UnsavedGuardContext.Provider>
            </div>
          );
        })}
      </section>
    );
  });
}
