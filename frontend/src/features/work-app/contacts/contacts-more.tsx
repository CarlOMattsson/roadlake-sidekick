import { useId, useState, type RefObject } from "react";
import type { WorkLabels } from "../shared/labels";
import { MoreIcon } from "../../mcp-apps/ui/icons";
import { Menu, menuButtonKeys, useMenuPopover } from "../../mcp-apps/ui/menu";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import { Switch } from "../../mcp-apps/ui/switch";
import {
  MenuUpdateReminder,
  useMoreMark,
} from "../../mcp-apps/update-reminder";
import { MenuLicenseRow, useLicenseMenu } from "../../mcp-apps/license-mark";

/** The state of the Contact list's ⋯: open or closed, its label and the id its button controls; `button` is the ⋯ itself. */
export function useContactsMore(
  label: string,
  button: RefObject<HTMLButtonElement | null>,
) {
  const [open, setOpen] = useState(false);
  const mark = useMoreMark(label);
  const panelId = useId();
  // The license coin asks (Control off): this ⋯ opens on its row.
  useLicenseMenu(button, () => setOpen(true));
  return { open, setOpen, mark, panelId };
}

export type ContactsMore = ReturnType<typeof useContactsMore>;

/** The ⋯ button; `className` is where it stands: the room head's tool box, or the list's own head row. */
export function ContactsMoreButton({
  more,
  buttonRef,
  className,
}: {
  more: ContactsMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
  className: string;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className={className}
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

/**
 * The list's ⋯ menu, a `Menu`: a popover under ⋯ with a mouse or in a frame at least 40 rem wide, the panel under the
 * head on a phone (where its entries keep the panel's own rows). It stays mounted while closed, so the archive switch
 * keeps its place.
 */
export function ContactsMenu({
  more,
  buttonRef: button,
  labels: t,
  includeArchived,
  onArchived,
  control,
}: {
  more: ContactsMore;
  buttonRef: RefObject<HTMLButtonElement | null>;
  labels: WorkLabels;
  includeArchived: boolean;
  onArchived: (include: boolean) => void;
  /** The last entry, which opens the Control room; absent: no entry. */
  control?: { label: string; onOpen: () => void };
}) {
  const popover = useMenuPopover();
  const { setOpen } = more;
  const entry = popover ? "sk-menu-item" : "work-contact-menu-item";
  function close() {
    setOpen(false);
    button.current?.focus();
  }
  return (
    <Menu
      id={more.panelId}
      open={more.open}
      anchor={button}
      panelClassName="work-contacts-panel work-contact-menu"
      onClose={() => setOpen(false)}
    >
      {/* The switch is the row's one control; its target is stretched over the whole row (contacts.css), so the words
          beside it toggle it too and the row is a 48 target. */}
      <div className={`${entry} work-contact-menu-switch`}>
        <span className="work-contact-menu-switch-text">{t.showArchived}</span>
        <Switch
          checked={includeArchived}
          onChange={onArchived}
          label={t.showArchived}
        />
      </div>
      <MenuShortcutsRow onChosen={close} />
      {control && (
        <button
          type="button"
          className={entry}
          onClick={() => {
            close();
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
