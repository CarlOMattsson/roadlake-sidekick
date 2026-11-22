import { createContext } from "react";

/**
 * What a room knows about where it is drawn, set by the Sidekick shell adapters.
 *
 * - `active` is false while the room is mounted but hidden (another room, or a cross-link above
 *   it). Keyboard shortcuts of a hidden room stay off.
 * - `framed` is true inside a full AppFrame the shell drew, so a room's own AppFrame draws nothing
 *   twice (no doubled padding).
 * - `room` and `view` name what the layer shows (the room and view of its entry, which may belong to
 *   another room than the pane: a contact reached from the journal is `contacts`/`contact`). The shared
 *   read error (ErrorNotice) words its heading from them (the room's failed-read heading), so a room's
 *   own files need not pass a text. Absent outside the shell: the notice then uses the general sentence.
 * - `heading` is the room's name when the shell draws no room strip (a host that offers one room: the mobile app),
 *   so a room that has a header row of its own writes the name there. Absent where the strip names the room.
 * - `backActions` is the end of the shell's Back row ("‹ Tavla … ✎ ⋯") while this layer is on top and
 *   the shell draws a Back; null otherwise. A view puts its pen and ⋯ there with `BackHeaderActions`
 *   (back-header.tsx) instead of on its title row.
 * - `headSlot` is the shell's one-row head in a wide frame (≥ 64rem) while this layer is on top; null otherwise. The
 *   room's `RoomHead` (room-head.tsx) draws its tabs and tools there, after the room strip, instead of in its own row.
 *   In a split pane the list holds it, not the record beside it.
 * - `pane` is the layer's place in a wide frame's split (ui/split-layout.tsx, desktop spec 2.1): `list` with a record
 *   or the hints beside it, `detail` beside the list, `drawer` over a wide view, `single` alone (absent: alone too).
 *   In a split pane `backActions` is the detail's own head, not the shell's Back row.
 * - `beside` is, on a list, the record open beside it (recordKey); its row is drawn chosen (useRecordRow).
 * - `asideSlot` is, on a list with no record open, the place beside it that SplitAside fills; null otherwise.
 * - `setLayout` lets a list say what it is now (useListLayout): a column, or a wide view (Status's columns) that a
 *   record lies over as a drawer.
 */
export type RoomSurface = {
  active: boolean;
  framed: boolean;
  room?: string;
  view?: string;
  heading?: string;
  backActions?: HTMLElement | null;
  headSlot?: HTMLElement | null;
  pane?: "single" | "list" | "detail" | "drawer";
  beside?: string;
  asideSlot?: HTMLElement | null;
  setLayout?: (layout: "list" | "wide") => void;
};

export const RoomSurfaceContext = createContext<RoomSurface>({
  active: true,
  framed: false,
});

/**
 * The host's message function (ui/message) for views deep in a room's stack that the room does not reach with props
 * (the Contacts room's list and Contact). Absent when the host offers no messages; a view then shows its example as
 * text.
 */
export const RoomMessageContext = createContext<
  ((text: string) => Promise<boolean>) | undefined
>(undefined);
