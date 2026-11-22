import { useId, useState, type RefObject } from "react";
import type { JournalLabels } from "./labels";
import { Menu, menuButtonKeys } from "../mcp-apps/ui/menu";
import { MenuUpdateReminder, useMoreMark } from "../mcp-apps/update-reminder";
import {
  MenuLicenseRow,
  useLicenseInMenu,
  useLicenseMenu,
} from "../mcp-apps/license-mark";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { MoreIcon } from "../mcp-apps/ui/icons";
import { MenuShortcutsRow } from "../mcp-apps/ui/shortcut-help";

/**
 * The day view's ⋯ menu: `control` (or the host's own settings), and the update reminder and the license row
 * when Control is off and the card is full size. `hasMore` says whether the menu has anything to hold.
 */
export function useDayMore(
  labels: JournalLabels,
  fullscreen: boolean,
  control: HostSettingsEntry | undefined,
  button: RefObject<HTMLButtonElement | null>,
) {
  const [open, setOpen] = useState(false);
  const mark = useMoreMark(labels.moreActions);
  const licenseInMenu = useLicenseInMenu();
  // The license coin asks (Control off): this ⋯ opens on its row.
  useLicenseMenu(button, () => setOpen(true));
  const panelId = useId();
  const hasMore =
    Boolean(control) || (fullscreen && (mark.inMenu || licenseInMenu));
  return { open, setOpen, mark, panelId, hasMore, control };
}

export type DayMore = ReturnType<typeof useDayMore>;

export function DayMoreButton({
  more,
  buttonRef,
}: {
  more: DayMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="sk-iconbtn sk-room-head__tool journal-day-more"
      aria-label={more.mark.label}
      aria-expanded={more.open}
      aria-controls={more.panelId}
      onClick={() => more.setOpen(!more.open)}
      onKeyDown={menuButtonKeys(more.open, more.setOpen)}
    >
      <MoreIcon />
      {more.mark.dot}
    </button>
  );
}

/** The room's ⋯ menu as Work's: a popover under ⋯ with a mouse or in a wide frame, the card under the head on a phone. */
export function DayMorePanel({
  more,
  buttonRef,
}: {
  more: DayMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
}) {
  const { control } = more;
  return (
    <Menu
      id={more.panelId}
      open={more.open}
      anchor={buttonRef}
      onClose={() => more.setOpen(false)}
    >
      <MenuShortcutsRow
        onChosen={() => {
          more.setOpen(false);
          buttonRef.current?.focus();
        }}
      />
      {control && (
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            more.setOpen(false);
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
