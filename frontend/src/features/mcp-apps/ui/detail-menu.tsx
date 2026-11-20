import { useRef, type RefObject } from "react";
import { Menu, MenuItem } from "./menu";

type MenuChoice = { label: string; onChoose: () => void };
type MenuToggle = MenuChoice & { pressed: boolean };

/**
 * The menu of a detail view's ⋯ button (the button sits in the Back row of the Task and Project frames), a `Menu`:
 * a popover under the button with a mouse or in a wide frame, the panel under the title on a phone. `edit` first
 * (design system §3, back row), then the record's mark, then `archive` (Restore for an archived record) in the text
 * colour: Restore undoes it, so it writes at once and the page shows its receipt. Only a deletion is drawn in the
 * danger colour, last. Escape, Tab or a press outside closes it; `onClose` gives the focus back to ⋯.
 */
export function DetailMenu({
  id,
  anchor,
  busy,
  edit,
  toggle,
  archive,
  remove,
  onClose,
}: {
  id: string;
  /**
   * The ⋯ button: the popover stands under it and the focus returns to it. Absent: the panel under the title at every
   * width (the Contact's, until its head moves to the shared room head).
   */
  anchor?: RefObject<HTMLElement | null>;
  busy: boolean;
  /** The `edit` entry, first in the menu; left out for an archived (read-only) record. */
  edit?: MenuChoice;
  /** A mark the record carries or not (a Task's "Möjlig med AI"): pressed while it is set, ticked at the entry's end. */
  toggle?: MenuToggle;
  /** An `archive`, or a `restore` for an archived record; no question first, because Restore and `undo` undo it. */
  archive?: MenuChoice;
  /** A Task's `deleteTask` in the danger colour; no question first, because the trash and `undo` undo it. */
  remove?: MenuChoice;
  onClose: () => void;
}) {
  const none = useRef<HTMLElement>(null);
  return (
    <Menu
      id={id}
      anchor={anchor ?? none}
      inFlow={!anchor}
      panelClassName="work-contact-menu"
      onClose={onClose}
    >
      {edit && (
        <MenuItem label={edit.label} onChoose={edit.onChoose} disabled={busy} />
      )}
      {toggle && (
        <MenuItem
          label={toggle.label}
          onChoose={toggle.onChoose}
          disabled={busy}
          pressed={toggle.pressed}
        />
      )}
      {archive && (
        <MenuItem
          label={archive.label}
          onChoose={archive.onChoose}
          disabled={busy}
        />
      )}
      {remove && (
        <MenuItem
          label={remove.label}
          onChoose={remove.onChoose}
          disabled={busy}
          danger
        />
      )}
    </Menu>
  );
}
