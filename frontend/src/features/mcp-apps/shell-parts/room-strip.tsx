import {
  useId,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactNode,
} from "react";

import { roomEnabled } from "@/features/mcp-apps/enabled-rooms";
import {
  MORE_ROOM_IDS,
  PRIMARY_ROOM_IDS,
  type RoomId,
} from "@/features/mcp-apps/router";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import { ChevronDownIcon } from "@/features/mcp-apps/ui/icons";
import {
  Menu,
  MenuItem,
  menuButtonKeys,
  openMenuByKey,
} from "@/features/mcp-apps/ui/menu";

/**
 * What the room strip shows (designsystem §3 "Rumsremsan"): the rooms used several times a week in cells of their own,
 * then the last cell, "Mer ⌄", with the rooms used about once a week or less as rows of the one menu (ui/menu.tsx), a
 * popover with a mouse or in a wide frame and a panel over the room on a phone. A room this instance leaves out
 * (SIDEKICK_ENABLED_ROOMS) is in neither; a Mer with no room is not drawn, and a strip of one room names nothing.
 *
 * While a room of Mer is open the Mer cell carries that room's name and the raised pill, so the place reads as clearly
 * as in the other rooms, and it is the strip's tab stop. The menu holds rooms only; tools stay in each room's ⋯.
 *
 * The Mer cell and its menu come apart, as the room picker's do: the cell stands in the strip's row of tabs (it takes
 * part in their roving focus and is measured with them), the menu on a line of its own under the bar.
 */
export function useRoomStrip({
  primary = PRIMARY_ROOM_IDS,
  more = MORE_ROOM_IDS,
  allowed,
  active,
  inControl,
  labels,
  onChoose,
}: {
  /** The rooms with a cell of their own, in order, before the instance's own choice (PRIMARY_ROOM_IDS). */
  primary?: readonly RoomId[];
  /** The rooms of Mer, in order, before the instance's own choice (MORE_ROOM_IDS). */
  more?: readonly RoomId[];
  /** False: the host draws no strip. */
  allowed: boolean;
  /** The room on screen, and whether Control is open over it (no room is marked then). */
  active: RoomId;
  inControl: boolean;
  labels: SidekickShellLabels;
  onChoose: (room: RoomId) => void;
}): {
  /** More than one room to lead to, and a host that draws the strip. */
  strip: boolean;
  /** The rooms with a cell of their own. */
  rooms: readonly RoomId[];
  /** Every room of the strip, cells first: what the narrow room picker lists. */
  pickRooms: readonly RoomId[];
  /** The room cell marked as the place the user is at; undefined while it is a room of Mer, or Control. */
  current: RoomId | undefined;
  /** The room cell that is the strip's one tab stop; undefined when it is the Mer cell. */
  tabStop: RoomId | undefined;
  /** The Mer cell and its menu; both null when Mer has no room. */
  moreParts: { cell: ReactNode; menu: ReactNode };
  /** Opens the Mer menu from a shortcut (`g 5`); undefined when there is no Mer cell. */
  openMore: (() => void) | undefined;
} {
  const [open, setOpen] = useState(false);
  const button = useRef<HTMLButtonElement>(null);
  const menuId = useId();

  const rooms = primary.filter((room) => roomEnabled(room));
  const moreRooms = more.filter((room) => roomEnabled(room));
  const pickRooms = [...rooms, ...moreRooms];
  const current = !inControl && rooms.includes(active) ? active : undefined;
  const moreCurrent =
    !inControl && moreRooms.includes(active) ? active : undefined;
  const base = {
    strip: allowed && pickRooms.length > 1,
    rooms,
    pickRooms,
    current,
    tabStop:
      current ?? (moreCurrent || rooms.length === 0 ? undefined : rooms[0]),
  };
  if (moreRooms.length === 0)
    return {
      ...base,
      moreParts: { cell: null, menu: null },
      openMore: undefined,
    };

  const name = moreCurrent ? labels.rooms[moreCurrent] : labels.more;
  const keys = menuButtonKeys(open, setOpen);

  function onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
    keys(event);
    // ↑ and ↓ open the menu here; the strip's roving focus must not move on as well.
    if (event.defaultPrevented) event.stopPropagation();
  }

  function choose(room: RoomId) {
    // The focus waits on the cell; the shell moves it on to the room's heading when the room changes.
    button.current?.focus({ preventScroll: true });
    setOpen(false);
    onChoose(room);
  }

  const cell = (
    <button
      ref={button}
      type="button"
      className="sk-rooms__tab sk-rooms__more"
      data-label={name}
      aria-label={moreCurrent ? labels.moreWith(name) : undefined}
      aria-current={moreCurrent ? "page" : undefined}
      aria-expanded={open}
      aria-controls={menuId}
      tabIndex={base.tabStop === undefined ? 0 : -1}
      onClick={() => setOpen(!open)}
      onKeyDown={onKeyDown}
    >
      <span className="sk-rooms__more-name">
        {name}
        <ChevronDownIcon size={16} />
      </span>
    </button>
  );

  const menu = open ? (
    <Menu
      id={menuId}
      anchor={button}
      align="start"
      overlay
      label={labels.moreMenu}
      className="sk-rooms__more-menu"
      panelClassName="sk-menu-panel sk-rooms__more-panel"
      onClose={() => setOpen(false)}
    >
      {moreRooms.map((room) => (
        <MenuItem
          key={room}
          label={labels.rooms[room]}
          current={room === moreCurrent}
          onChoose={() => choose(room)}
        />
      ))}
    </Menu>
  ) : null;

  return {
    ...base,
    moreParts: { cell, menu },
    openMore: () => openMenuByKey(button.current, setOpen),
  };
}
