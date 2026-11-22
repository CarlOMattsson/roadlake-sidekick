import type { ReactNode, RefObject } from "react";
import { Menu, menuButtonKeys } from "../../mcp-apps/ui/menu";
import { MoreIcon } from "../../mcp-apps/ui/icons";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import { MenuUpdateReminder } from "../../mcp-apps/update-reminder";
import { MenuLicenseRow } from "../../mcp-apps/license-mark";
import type { HostSettingsEntry } from "../../mcp-apps/room-types";

/**
 * The room's ⋯ button: the family's icon button in a 44 box (`sk-room-head__tool`, so it stands on the head's fixed
 * place), with the menu keys (↓ opens on the first entry, ↑ on the last).
 */
export function MoreButton({
  label,
  dot,
  open,
  menuId,
  buttonRef,
  onOpenChange,
}: {
  label: string;
  /** The update reminder's dot (useMoreMark). */
  dot?: ReactNode;
  open: boolean;
  menuId: string;
  buttonRef: RefObject<HTMLButtonElement | null>;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="shopping-more-trigger sk-iconbtn sk-room-head__tool"
      aria-label={label}
      aria-expanded={open}
      aria-controls={open ? menuId : undefined}
      onClick={() => onOpenChange(!open)}
      onKeyDown={menuButtonKeys(open, onOpenChange)}
    >
      <MoreIcon />
      {dot}
    </button>
  );
}

/**
 * The ⋯ menu of the room (designsystem §3): the shared `Menu`, a popover under ⋯ with a mouse or in a wide frame, the
 * family's panel under the head on a phone. The room's entries first, then "Kortkommandon ?" (fine pointer), then
 * Control's `title` (or the host's own settings), the update reminder and the license row. Escape, Tab or a press
 * outside closes it; a chosen entry closes it with the focus back on ⋯.
 */
export function MoreMenu({
  id,
  anchor,
  control,
  onClose,
  children,
}: {
  id: string;
  /** The ⋯ button: the popover stands under it and the focus returns to it. */
  anchor: RefObject<HTMLButtonElement | null>;
  /** The last entry: Control, or the host's own settings (the phone). */
  control?: HostSettingsEntry;
  onClose: () => void;
  /** The entries that come before it. */
  children?: ReactNode;
}) {
  return (
    <Menu id={id} anchor={anchor} onClose={onClose}>
      {children}
      <MenuShortcutsRow
        onChosen={() => {
          onClose();
          anchor.current?.focus();
        }}
      />
      {control && (
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            onClose();
            anchor.current?.focus();
            control.onOpen();
          }}
        >
          {control.label}
        </button>
      )}
      <MenuUpdateReminder />
      <MenuLicenseRow />
    </Menu>
  );
}
