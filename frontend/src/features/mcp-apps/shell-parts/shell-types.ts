import type { ComponentType } from "react";

import type { AppLocale } from "@/features/mcp-apps/app-locale";
import type { HostFeatures } from "@/features/mcp-apps/bridge";
import type { NavEntry } from "@/features/mcp-apps/nav-state";
import type { RoomId, StripRoomId } from "@/features/mcp-apps/router";

/**
 * What the shell hands a room. A room draws `entry` and nothing else about navigation.
 *
 * - `entry` is what to show now: the room's root, or the top of its stack. It may belong to another
 *   room (a contact reached from the journal is drawn by the contacts room inside the journal's pane).
 * - `full` is false in an inline card. Inline, a room draws its compact card and never navigates.
 * - `visible` is false while the pane is hidden. A hidden pane stays mounted, so state survives.
 * - `refreshKey` is kept per layer (a root or a step above it), not per room. It changes when that
 *   layer should read its data again as it is shown (a write in another layer touched its domain, or it
 *   was hidden for more than a minute). A room reloads when it changes, without resetting its view.
 * - `navigate` pushes a cross-link on the stack of the room the user is in. Every step into a record
 *   (a Task, a Contact, a post) goes through it, so the shell's one Back leads out of it, one step at
 *   a time. It is undefined when the host cannot proxy tool calls (and inline): the room then draws no
 *   cross-links and keeps its own inner navigation and Back.
 * - `markDirty` tells the shell which domains a write may have changed, so other rooms read again.
 *   The caller's own pane is treated as up to date.
 *
 * In full mode the shell draws the AppFrame; a room must not wrap itself in one.
 */
export type ShellRoomProps = {
  entry: NavEntry;
  full: boolean;
  visible: boolean;
  refreshKey: number;
  navigate?: (target: NavEntry, options?: { replace?: boolean }) => void;
  markDirty: (domains: readonly RoomId[]) => void;
  locale: AppLocale;
  /** bridge.sendMessage, present only when the host offers ui/message. */
  sendMessage?: (text: string) => Promise<boolean>;
};
export type RoomRegistry = Record<RoomId, ComponentType<ShellRoomProps>>;

export type SidekickShellProps = {
  locale: AppLocale;
  /** One component per room. Each room that is built registers its component here. */
  rooms: RoomRegistry;
  /**
   * Where the card opened: the room, view and the tool result that opened it. Read once on mount;
   * the caller changes `key` when a new tool result re-roots the app.
   */
  start: NavEntry;
  /**
   * A record to show on top of the start room at once, when a room that asked for the full view
   * wants one record shown there (an entry of the journal's day glance). Pushed when it changes.
   */
  openAt?: NavEntry;
  /** True in fullscreen or in the expanded inline view. The strip exists only then. */
  full: boolean;
  /**
   * Present when the full view is only our own expansion (the host does not show fullscreen): a
   * `collapse` button in the view then folds it back into the card, so the user never gets stuck in it.
   */
  onCollapse?: () => void;
  /** From bridge.getFeatures(). */
  features: HostFeatures;
  /** bridge.updateModelContext. Called on a room change and on a cross-link (full mode only). */
  onModelContext?: (summary: string) => void;
  /** bridge.sendMessage. Used by the reserve strip when the host cannot proxy tool calls. */
  onSendMessage?: (text: string) => Promise<boolean>;
  /**
   * False hides the room strip (a host that offers one room only: the mobile app's Today). Cross-links and Back stay.
   * Defaults to true.
   */
  strip?: boolean;
  /**
   * The rooms the strip and the narrow room picker offer, in order (a host that serves only some rooms: the phone).
   * Defaults to every strip room. Other rooms stay reachable by cross-links.
   */
  stripRooms?: readonly StripRoomId[];
  /**
   * Lets the host own system Back (Android). The shell calls this with a handler that returns true when it went back
   * one layer and false when it is at the root (the host then leaves the app), and with undefined on unmount. The MCP
   * entry does not pass it.
   */
  registerBack?: (handler: (() => boolean) | undefined) => void;
  /**
   * A host that was away for a while (the Android app came back to the foreground) raises this number. Every layer then
   * counts as hidden for more than a minute: the one shown reads again in place at once, the others when they are shown.
   * The value at mount is not a request. The MCP entry does not pass it.
   */
  staleTick?: number;
};
