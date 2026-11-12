import type { HostBridge } from "./bridge";
import type { RoomId } from "./router";

/**
 * The room contract of the Sidekick app.
 * A room is one React component per domain: JournalRoom, ShoppingRoom, ControlRoom, WorkRoom and
 * ContactsRoom. A room owns all state of its domain, takes every read and write from `transport`,
 * and knows nothing about the host bridge, the router or other rooms. The thin entries (and later the
 * shell) mount rooms; a room may be mounted hidden and then reads for itself when `initial` is absent.
 */

/**
 * Where a link inside a room wants to go. Rooms ask; the shell decides and pushes onto the room's
 * stack. `label` is a short name for the model-context line (a contact name, a task title), never
 * journal text. RoomId has one source, router.ts.
 */
export type RoomTarget = {
  room: RoomId;
  view?: string;
  id?: string;
  label?: string;
  /** The list view the target is opened from ("agenda", "board", "hierarchy"); names the Back header when the record below has no name. */
  from?: string;
  /** True: the target takes the place of the layer the room is on (a finalized draft becomes its entry). */
  replace?: boolean;
  /** A tool-result-like payload for the target's room, when the caller already holds one (rare). */
  data?: unknown;
};

/** `inline` is the card in the conversation, `full` is fullscreen or the expanded inline view. */
export type RoomMode = "inline" | "full";

/**
 * What a room may ask of the host: read or write through `tools/call`, ask for another display
 * mode, and tell the host model a short line. The host bridge satisfies it as it is.
 */
export type RoomTransport = Pick<
  HostBridge,
  "call" | "requestDisplayMode" | "updateModelContext"
> & {
  /**
   * Whether the host can answer `call(name, ...)` at all. Absent: every tool (the Claude host proxies the whole
   * server). A host with a closed list of routes (the mobile app) answers false for the rest, and a room then offers
   * no menu item, button or link whose tool is not there, as it does for a view that `availableViews` leaves out.
   */
  supportsTool?: (name: string) => boolean;
  /**
   * Whether the host can answer this very call, for a tool it answers only in part (the mobile app's update_task
   * takes only the completing change). Absent: `supportsTool` alone decides. Read it through `toolOffered`.
   */
  supportsCall?: (name: string, args: object) => boolean;
  /** What a host that works offline (the mobile app) offers; absent in Claude. */
  offline?: OfflineSupport;
};

/**
 * The mobile app's offline help (frontend/src/mobile/companion-transport.ts). A read that got no answer may be answered
 * from the phone's copy of what was last read, and a purchase that got no answer waits in the phone's outbox, which
 * sends it once a network exists. Only the Shopping room uses it.
 */
export type OfflineSupport = {
  /** When `result` is the phone's offline copy: the epoch millis it was read from the server. Else undefined. */
  readAt: (result: object) => number | undefined;
  /** The purchases waiting in the outbox: item id → the state that will be sent. */
  queuedPurchases: () => Promise<ReadonlyMap<string, boolean>>;
  /**
   * The ids of the Tasks whose completion waits in the outbox (ticked in the widget or the app, not yet sent), so a
   * room can draw them as done though the server still has them open. Absent where the host has no such outbox.
   */
  queuedCompletions?: () => Promise<ReadonlySet<string>>;
  /** Calls `listener` when a run of the outbox has ended; returns the unsubscribe. */
  onQueueChanged: (listener: () => void) => () => void;
};

export type RoomProps = {
  /**
   * The structuredContent of the newest tool result that opened this room. May be absent: a room
   * mounted hidden (or before any result) reads its own start view through `transport`.
   */
  initial?: unknown;
  /**
   * Changes when the room should read its data again because something elsewhere may have changed it
   * (a write in another room, or a long absence). The value at mount is not a request. A room reads
   * again IN PLACE: it keeps the open tab, column, day, detail, scroll and anything the user typed or
   * left unsaved, and replaces only the data when the answer arrives. It must not remount or show a skeleton.
   */
  refreshKey?: number;
  /** The newest tool result was an error (isError). `initial` is then its structuredContent, often absent. */
  initialError?: boolean;
  /**
   * Counts delivered tool results. A room treats a changed `resultId`, `initial` or `initialError`
   * as a new result that re-roots it; this also covers two error results with no content.
   */
  resultId?: number;
  /** A named start view when the router knows one and `initial` carries none (for example "board"). Unknown names are ignored. */
  view?: string;
  mode: RoomMode;
  /**
   * True when the host offers fullscreen and the room is not there already. Open then asks
   * `transport.requestDisplayMode("fullscreen")`; otherwise a room expands its full view inline.
   */
  fullscreenAvailable?: boolean;
  transport: RoomTransport;
  /**
   * The views of this room that the host can serve (for the Work room: "agenda", "board", "hierarchy").
   * Absent: every view. A room offers no tab, menu item or link for a view that is not listed; a host
   * whose server has no route for a view lists the others only.
   */
  availableViews?: readonly string[];
  /** Sends a message to Claude in the chat (ui/message). Absent when the host offers no messages. */
  sendMessage?: (text: string) => Promise<boolean>;
  /** A link to another room or view. Absent: the room shows no cross links. */
  onNavigate?: (target: RoomTarget) => void;
  /** A write may have changed these domains ("work", "journal", "contacts", ...); the shell re-reads other rooms. */
  onDirty?: (domains: string[]) => void;
  /**
   * The room asked the host for another display mode and the host granted it. The caller may switch
   * `mode` at once instead of waiting for the host's own context change. Optional; a caller may ignore it.
   */
  onModeGranted?: (mode: RoomMode, target?: RoomTarget) => void;
  /** False while the room is mounted but hidden. Defaults to true. */
  active?: boolean;
  /**
   * The host's own settings, in Control's place at the end of the room's ⋯ menu (the phone's "Inställningar"). Given
   * only by a host that has settings of its own; Claude gives none.
   */
  hostSettings?: HostSettingsEntry;
};

/** A menu entry the host draws its own screen for: the label, and what opens it. */
export type HostSettingsEntry = { label: string; onOpen: () => void };

/** The mode a room is in for a host display mode: fullscreen is `full`; inline and pip are `inline`. */
export function roomModeOf(displayMode: string | undefined): RoomMode {
  return displayMode === "fullscreen" ? "full" : "inline";
}

/** Whether the host offers fullscreen and the app is not in it. */
export function fullscreenOffered(
  availableDisplayModes: string[] | undefined,
  displayMode: string | undefined,
): boolean {
  return (
    (availableDisplayModes ?? []).includes("fullscreen") &&
    displayMode !== "fullscreen"
  );
}
