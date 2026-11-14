import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import {
  isRecordEntry,
  type NavEntry,
  type NavState,
} from "@/features/mcp-apps/nav-state";
import { ROOM_IDS, type RoomId } from "@/features/mcp-apps/router";

/** A room that has been hidden longer than this is read again when it is shown. */
export const STALE_AFTER_MS = 60_000;
/** The model-context line never carries a longer name than this. */
const LABEL_MAX_CHARS = 80;

/**
 * "Visar Kontakter › Anna Andersson (id 123)". Short, never journal text: a journal entry is
 * named by its id only, and a label is cut to 80 characters.
 */
export function modelContextLine(
  labels: SidekickShellLabels,
  active: RoomId,
  entry: NavEntry,
): string {
  const parts = [labels.rooms[active]];
  if (entry.room !== active) parts.push(labels.rooms[entry.room]);
  const label =
    entry.room === "journal"
      ? undefined
      : entry.label?.replace(/\s+/g, " ").trim();
  if (label) parts.push(Array.from(label).slice(0, LABEL_MAX_CHARS).join(""));
  const id = entry.id ? ` (id ${entry.id})` : "";
  return `${labels.viewing} ${parts.join(" › ")}${id}`;
}

/** The scroll memory key of the layer a room shows now. */
export function layerKey(state: NavState, room: RoomId): string {
  return `${room}:${state.stacks[room].length}`;
}

function entryKey(entry: NavEntry): string {
  return `${entry.room}:${entry.view}:${entry.id ?? ""}`;
}
export function scrollTop(): number {
  return document.scrollingElement?.scrollTop ?? 0;
}
export function setScrollTop(top: number) {
  // jsdom has no layout; only call where the browser can scroll.
  if (document.scrollingElement) document.scrollingElement.scrollTop = top;
}

/** The clock behind one name, so the hooks lint sees an event-time read, not a render-time one. */
export function clockNow(): number {
  return Date.now();
}

/** What the shell remembers about one mounted layer: the write counts it has read up to. */
export type LayerBook = {
  seen: Record<RoomId, number>;
  hiddenAt: number | null;
};

/** One drawn layer of a pane: the room's root or a step above it. */
export type Layer = { id: string; room: RoomId; entry: NavEntry; top: boolean };

/**
 * The layers of a pane, oldest first. The id stays the same while the layer is on the stack, also when
 * the stack is cut at STACK_LIMIT (an index in the id would remount every layer on each step then).
 */
export function layersOf(state: NavState, room: RoomId): Layer[] {
  const entries = [state.roots[room], ...state.stacks[room]];
  const used = new Set<string>();
  return entries.map((entry, index) => {
    let key = index === 0 ? `${entryKey(entry)}:root` : entryKey(entry);
    if (used.has(key)) key = `${key}#${index}`;
    used.add(key);
    return {
      id: `${room}|${key}`,
      room,
      entry,
      top: index === entries.length - 1,
    };
  });
}

/**
 * The name of the layer a Back returns to: a record's own name ("Anna"), else the list the top entry was opened from
 * (`project` for a Project opened from that tab), else the view's name (`status` or `task`), else the name of its
 * room.
 */
export function backName(labels: SidekickShellLabels, nav: NavState): string {
  const stack = nav.stacks[nav.active];
  // The entry below the top one; the root when the stack holds one entry or none.
  const parent = stack[stack.length - 2] ?? nav.roots[nav.active];
  if (isRecordEntry(parent) && parent.label) return parent.label;
  const top = stack[stack.length - 1];
  // Control is a step of the room it was opened from: Back names that room, not its view.
  if (top?.room === "control") return labels.rooms[parent.room];
  const origin = top?.from;
  if (origin !== undefined && !isRecordEntry(parent)) {
    const listed = labels.viewNames[`${parent.room}:${origin}`];
    if (listed !== undefined) return listed;
  }
  return (
    labels.viewNames[`${parent.room}:${parent.view}`] ??
    labels.rooms[parent.room]
  );
}

export function zeroes(): Record<RoomId, number> {
  return Object.fromEntries(ROOM_IDS.map((room) => [room, 0])) as Record<
    RoomId,
    number
  >;
}
