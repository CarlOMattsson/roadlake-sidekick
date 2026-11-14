import type { ReactNode } from "react";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import { MenuUpdateReminder } from "../../mcp-apps/update-reminder";
import { MenuLicenseRow } from "../../mcp-apps/license-mark";
import type { HostSettingsEntry } from "../../mcp-apps/room-types";

/**
 * The ⋯ menu of the room (designsystem §3): the family's panel under the head, one 44 row per entry, the last entry
 * The Control room's `title` (or the host's own settings). `onClose` closes it when an entry is chosen; `onEscape` runs on
 * Escape from inside it, where the room gives the focus back to ⋯.
 */
export function MoreMenu({
  control,
  onClose,
  onEscape,
  children,
}: {
  /** The last entry: Control, or the host's own settings (the phone). */
  control?: HostSettingsEntry;
  onClose: () => void;
  onEscape: () => void;
  /** The entries that come before it. */
  children?: ReactNode;
}) {
  return (
    <KeyScope className="sk-menu-panel" onEscape={onEscape}>
      {children}
      {control && (
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            onClose();
            control.onOpen();
          }}
        >
          {control.label}
        </button>
      )}
      <MenuUpdateReminder />
      <MenuLicenseRow />
    </KeyScope>
  );
}
