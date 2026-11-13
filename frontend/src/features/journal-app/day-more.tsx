import { useId, useState, type RefObject } from "react";
import type { JournalLabels } from "./labels";
import { KeyScope } from "../mcp-apps/ui/key-scope";
import { MenuUpdateReminder, useMoreMark } from "../mcp-apps/update-reminder";
import {
  MenuLicenseRow,
  useLicenseInMenu,
  useLicenseMenu,
} from "../mcp-apps/license-mark";
import type { HostSettingsEntry } from "../mcp-apps/room-types";
import { MoreIcon } from "../mcp-apps/ui/icons";

/**
 * The day view's ⋯ menu: "Kontroll" (or the host's own settings), and the update reminder and the license row
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
      className="sk-iconbtn journal-day-more"
      aria-label={more.mark.label}
      aria-expanded={more.open}
      aria-controls={more.panelId}
      onClick={() => more.setOpen(!more.open)}
    >
      <MoreIcon />
      {more.mark.dot}
    </button>
  );
}

/** The room's ⋯ menu as Work's (a card under the head, 44 rows). */
export function DayMorePanel({
  more,
  buttonRef,
}: {
  more: DayMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
}) {
  const { control } = more;
  return (
    <KeyScope
      id={more.panelId}
      className="journal-more-panel"
      hidden={!more.open}
      onEscape={() => {
        more.setOpen(false);
        buttonRef.current?.focus();
      }}
    >
      {control && (
        <button
          type="button"
          className="journal-more-item"
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
    </KeyScope>
  );
}
