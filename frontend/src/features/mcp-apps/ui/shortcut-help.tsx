import {
  Fragment,
  useContext,
  useEffect,
  useId,
  useRef,
  type ReactNode,
} from "react";

import { CloseIcon } from "./icons";
import {
  shortcutKeyParts,
  ShortcutHelpOpenerContext,
  type ShortcutHelpGroup,
} from "./shortcut-registry";
import { finePointer } from "./shortcuts";
import { Switch } from "./switch";
import "./shortcut-help.css";

/**
 * The keyboard help sheet (designsystem: "Tangentbord"): a modal dialog listing the shortcut groups the rooms
 * registered (shortcut-registry.ts), with the switch for single-character shortcuts last. Esc, the × and a click on
 * the backdrop close it; focus goes to the × on opening and back to what had it on closing. Esc is taken here
 * (default prevented, propagation stopped) so no other layer or the host sees the same press.
 */
export type ShortcutHelpProps = {
  open: boolean;
  onClose: () => void;
  title: string;
  closeLabel: string;
  groups: readonly ShortcutHelpGroup[];
  charKeys?: { label: string; on: boolean; onChange: (on: boolean) => void };
};

export function ShortcutHelp({
  open,
  onClose,
  title,
  closeLabel,
  groups,
  charKeys,
}: ShortcutHelpProps): ReactNode {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const closeRef = useRef<HTMLButtonElement>(null);
  const returnFocusRef = useRef<Element | null>(null);
  const openRef = useRef(open);
  const onCloseRef = useRef(onClose);
  const titleId = useId();

  useEffect(() => {
    openRef.current = open;
    onCloseRef.current = onClose;
  });

  // Open and close the native dialog from the prop.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    if (open && !dialog.open) {
      returnFocusRef.current = document.activeElement;
      // jsdom and older engines lack showModal: the open attribute shows the dialog without the top layer.
      if (typeof dialog.showModal === "function") dialog.showModal();
      else dialog.setAttribute("open", "");
      closeRef.current?.focus();
    } else if (!open && dialog.open) {
      if (typeof dialog.close === "function") dialog.close();
      else dialog.removeAttribute("open");
      const back = returnFocusRef.current;
      returnFocusRef.current = null;
      if (back instanceof HTMLElement && back.isConnected) back.focus();
    }
  }, [open]);

  // Esc closes through onClose and nothing else reacts to it; native listeners, so stopPropagation reaches the window.
  useEffect(() => {
    const dialog = dialogRef.current;
    if (!dialog) return;
    const take = (event: Event) => {
      event.preventDefault();
      event.stopPropagation();
      onCloseRef.current();
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") take(event);
    };
    // A close the dialog did on its own while the prop still says open (not one this component asked for).
    const onNativeClose = () => {
      if (openRef.current) onCloseRef.current();
    };
    // The backdrop is the dialog element itself, outside its content.
    const onClick = (event: MouseEvent) => {
      if (event.target === dialog) onCloseRef.current();
    };
    dialog.addEventListener("keydown", onKeyDown);
    dialog.addEventListener("cancel", take);
    dialog.addEventListener("close", onNativeClose);
    dialog.addEventListener("click", onClick);
    return () => {
      dialog.removeEventListener("keydown", onKeyDown);
      dialog.removeEventListener("cancel", take);
      dialog.removeEventListener("close", onNativeClose);
      dialog.removeEventListener("click", onClick);
    };
  }, []);

  return (
    <dialog
      ref={dialogRef}
      className="sk-shortcut-help"
      aria-labelledby={titleId}
    >
      <div className="sk-shortcut-help__body">
        <div className="sk-shortcut-help__head">
          <h2 id={titleId} className="sk-shortcut-help__title">
            {title}
          </h2>
          <button
            ref={closeRef}
            type="button"
            className="sk-iconbtn"
            aria-label={closeLabel}
            onClick={onClose}
          >
            <CloseIcon />
          </button>
        </div>
        {groups.map((group) => (
          <section key={group.id} className="sk-shortcut-help__group">
            <h3 className="sk-shortcut-help__group-title">{group.title}</h3>
            <dl className="sk-shortcut-help__list">
              {group.entries.map((entry) => (
                <div key={entry.label} className="sk-shortcut-help__row">
                  <dt className="sk-shortcut-help__keys">
                    {entry.keys.map((binding, index) => (
                      <Fragment key={binding}>
                        {index > 0 ? (
                          <span
                            className="sk-shortcut-help__or"
                            aria-hidden="true"
                          >
                            /
                          </span>
                        ) : null}
                        <span className="sk-shortcut-help__combo">
                          {shortcutKeyParts(binding).map((part, at) => (
                            <kbd key={`${at}-${part}`}>{part}</kbd>
                          ))}
                        </span>
                      </Fragment>
                    ))}
                  </dt>
                  <dd className="sk-shortcut-help__label">{entry.label}</dd>
                </div>
              ))}
            </dl>
          </section>
        ))}
        {charKeys ? (
          <div className="sk-shortcut-help__row sk-shortcut-help__switch">
            <span className="sk-shortcut-help__label">{charKeys.label}</span>
            <Switch
              checked={charKeys.on}
              onChange={charKeys.onChange}
              label={charKeys.label}
            />
          </div>
        ) : null}
      </div>
    </dialog>
  );
}

/**
 * "Kortkommandon ?" in a room's ⋯ (desktop spec 2.6), last before Control: only with a fine pointer (a keyboard is then
 * at hand) and only where the shell offers the help. `onChosen` closes the menu first, so the focus is back on ⋯ when the
 * help opens and returns there when it closes.
 */
export function MenuShortcutsRow({ onChosen }: { onChosen: () => void }) {
  const opener = useContext(ShortcutHelpOpenerContext);
  if (!opener || !finePointer()) return null;
  return (
    <button
      type="button"
      className="sk-menu-item sk-menu-item--keys"
      aria-keyshortcuts="?"
      onClick={() => {
        onChosen();
        opener.open();
      }}
    >
      {opener.label}
      <kbd className="sk-menu-item__key" aria-hidden="true">
        ?
      </kbd>
    </button>
  );
}
