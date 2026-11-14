import { KeyScope } from "./key-scope";

type MenuChoice = { label: string; onChoose: () => void };

/**
 * The panel of a detail view's ⋯ button (the button sits in the Back row of the Contact, Task and Project frames).
 * It opens under the title with `edit` first (design system §3, back row; nicknames are edited there too),
 * then `archive` (Restore for an archived Contact) in the text colour: Restore undoes it, so it writes at once and the page
 * shows its receipt. Only a deletion is drawn in the danger colour. Only a Contact has an archive entry. Escape closes it.
 */
export function DetailMenu({
  id,
  busy,
  edit,
  archive,
  remove,
  onClose,
}: {
  id: string;
  busy: boolean;
  /** The `edit` entry, first in the menu; left out for an archived (read-only) Contact. */
  edit?: MenuChoice;
  /** A Contact's `archiveContact`, or `restoreContact` for an archived one; no question first, because Restore and `undo` undo it. */
  archive?: MenuChoice;
  /** A Task's `deleteTask` in the danger colour; no question first, because the trash and `undo` undo it. */
  remove?: MenuChoice;
  onClose: () => void;
}) {
  return (
    <KeyScope id={id} className="work-contact-menu" onEscape={onClose}>
      {edit && <MenuItem choice={edit} busy={busy} />}
      {archive && <MenuItem choice={archive} busy={busy} />}
      {remove && <MenuItem choice={remove} busy={busy} danger />}
    </KeyScope>
  );
}

function MenuItem({
  choice,
  busy,
  danger = false,
}: {
  choice: MenuChoice;
  busy: boolean;
  danger?: boolean;
}) {
  return (
    <button
      type="button"
      className={danger ? "sk-menu-item sk-menu-item--danger" : "sk-menu-item"}
      disabled={busy}
      onClick={choice.onChoose}
    >
      {choice.label}
    </button>
  );
}
