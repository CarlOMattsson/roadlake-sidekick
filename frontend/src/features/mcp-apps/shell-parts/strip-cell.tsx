import type { ReactNode } from "react";

import type { NavIcons } from "@/features/mcp-apps/nav-icons";
import type { StripRoomId } from "@/features/mcp-apps/router";
import {
  BasketIcon,
  CheckRingIcon,
  NotebookIcon,
  PeopleIcon,
  TilesIcon,
  type RoomIconProps,
} from "@/features/mcp-apps/ui/icons";

/** The glyph of every room the strip leads to (ui/icons.tsx); a room that joins the strip needs one here. */
const ROOM_GLYPHS: Record<StripRoomId, (props: RoomIconProps) => ReactNode> = {
  work: CheckRingIcon,
  journal: NotebookIcon,
  shopping: BasketIcon,
  contacts: PeopleIcon,
};

/**
 * What a cell of the room strip draws (designsystem §3 "Rumsremsan"): the name alone (`off`), a 20 glyph with the name
 * (`label`; and `auto`, where the styles draw the glyph in a phone's frame only) or the glyph alone (`only`). `room`
 * is the room whose glyph it is; without one it is the Mer cell at rest, four tiles. `stripCellNames` names a cell
 * whose name is not drawn.
 */
export function StripCellFace({
  icons,
  room,
  name,
}: {
  icons: NavIcons;
  room: StripRoomId | undefined;
  name: string;
}) {
  if (icons === "off") return name;
  const Glyph = room ? ROOM_GLYPHS[room] : TilesIcon;
  return (
    <>
      <Glyph size={20} />
      {icons === "only" ? null : <span className="sk-rooms__name">{name}</span>}
    </>
  );
}

/**
 * How a cell that an instance or an owner gave glyphs is named. `label` is its `aria-label`, the room's name whether
 * the face draws it or not. `tip` is its `title`, the tooltip a hovering pointer gets, for a cell that never draws its
 * name. Both undefined where the name is the face at every width that has room for it (`off`, `auto`).
 */
export function stripCellNames(
  icons: NavIcons,
  name: string,
): { label: string | undefined; tip: string | undefined } {
  return {
    label: icons === "label" || icons === "only" ? name : undefined,
    tip: icons === "only" ? name : undefined,
  };
}
