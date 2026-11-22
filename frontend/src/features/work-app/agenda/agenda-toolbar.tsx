import {
  useEffect,
  useId,
  useLayoutEffect,
  useRef,
  type ReactNode,
} from "react";
import { CloseIcon, MoreIcon } from "./agenda-icons";
import { Menu, menuButtonKeys } from "../../mcp-apps/ui/menu";
import {
  MenuUpdateReminder,
  useMoreMark,
} from "../../mcp-apps/update-reminder";
import { MenuLicenseRow, useLicenseMenu } from "../../mcp-apps/license-mark";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import type { WorkLabels } from "../shared/labels";
import "./agenda-toolbar.css";

/**
 * The search field of the fullscreen agenda, unfolded under the room head by its search icon (ui/room-head.tsx;
 * designsystem §3 "Skapa": a screen shows at most one text field, so the new-Task field closes while this one is open). It is 48 px
 * high with a × that closes it: closing clears the text and puts the focus back on the search icon. Escape closes too.
 * The caller owns the text and whether it is open. The field takes the focus when `focusTick` changes (the user
 * pressed the search icon), not whenever it shows again, so coming Back from a Task does not open the keyboard.
 */
export function AgendaSearch({
  id,
  label,
  closeLabel,
  query,
  onQuery,
  open,
  focusTick,
  onClose,
}: {
  id: string;
  /** Name and placeholder of the field: the `search` label of the work shell. */
  label: string;
  /** Name of the ×: the `closeSearch` label of the work shell. */
  closeLabel: string;
  query: string;
  onQuery: (query: string) => void;
  /** False hides the row (kept mounted). */
  open: boolean;
  /** A new value moves the focus into the field; the value at mount does not. */
  focusTick: number;
  onClose: () => void;
}) {
  const field = useRef<HTMLInputElement>(null);
  const seenTick = useRef(focusTick);
  useEffect(() => {
    if (focusTick === seenTick.current) return;
    seenTick.current = focusTick;
    field.current?.focus();
  }, [focusTick]);
  return (
    <div id={id} className="work-search" hidden={!open}>
      <input
        ref={field}
        type="search"
        className="work-search-field"
        aria-label={label}
        placeholder={label}
        value={query}
        enterKeyHint="search"
        autoComplete="off"
        onChange={(event) => onQuery(event.target.value)}
        onKeyDown={(event) => {
          if (event.key !== "Escape") return;
          event.preventDefault();
          event.stopPropagation();
          onClose();
        }}
      />
      <button
        type="button"
        className="work-search-close"
        aria-label={closeLabel}
        onClick={onClose}
      >
        <CloseIcon />
      </button>
    </div>
  );
}

/**
 * The "⋯" button of a Work tab, outermost in the room head (ui/room-head.tsx). It opens a `Menu` with the view's
 * rarer actions (saved views, `refresh`, and `control` last, designsystem §3 "Rumshuvud"): a popover under the button
 * with a mouse or in a wide frame, else (a phone) the panel under the tab row, at full width, in the page flow; the
 * button stays where it is. The caller owns the state (open or closed), because the view under it is remounted when a saved
 * view opens and this button is not. The panel stays mounted while closed (hidden), so what it holds keeps its status
 * and focus.
 */
export function AgendaMore({
  labels: t,
  open,
  onOpenChange,
  onRefresh,
  control,
  hidden = false,
  children,
}: {
  labels: WorkLabels;
  /** Hides the button and its menu (kept mounted, so an open menu keeps its state). */
  hidden?: boolean;
  open: boolean;
  onOpenChange: (open: boolean) => void;
  onRefresh: () => void;
  /**
   * The last item: `control`, which opens the Control room, or the host's own settings in its place (the phone's
   * settings). Absent when the host has neither. The focus returns to ⋯ before it opens, so a screen that closes
   * again can give it back there.
   */
  control?: { label: string; onOpen: () => void };
  /** The first item of the menu: the saved views bar. */
  children?: ReactNode;
}) {
  const panelId = useId();
  const more = useRef<HTMLButtonElement>(null);
  const mark = useMoreMark(t.moreActions);
  // The license coin asks (Control off): the ⋯ of the tab on screen opens on its row.
  useLicenseMenu(more, () => onOpenChange(true));
  function close() {
    onOpenChange(false);
    more.current?.focus();
  }
  // The menu can be closed from outside (a saved view opened): when it folds away while the focus sat in it, or was
  // dropped on the page, the focus goes back to ⋯ so a keyboard or screen reader user is not left on a hidden control.
  // A layout effect, so the focus is back in the same frame in every renderer, not after the next paint.
  const wasOpen = useRef(open);
  useLayoutEffect(() => {
    if (wasOpen.current && !open) {
      const focused = document.activeElement;
      const inPanel =
        focused instanceof Node &&
        document.getElementById(panelId)?.contains(focused);
      if (!focused || focused === document.body || inPanel)
        more.current?.focus();
    }
    wasOpen.current = open;
  }, [open, panelId]);
  return (
    <div className="work-agenda-more" hidden={hidden}>
      <button
        ref={more}
        type="button"
        className="sk-iconbtn sk-room-head__tool"
        aria-label={mark.label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onOpenChange(!open)}
        onKeyDown={menuButtonKeys(open, onOpenChange)}
      >
        <MoreIcon />
        {mark.dot}
      </button>
      <Menu
        id={panelId}
        open={open}
        anchor={more}
        onClose={() => onOpenChange(false)}
      >
        {children}
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            onRefresh();
            close();
          }}
        >
          {t.refresh}
        </button>
        <MenuShortcutsRow onChosen={close} />
        {control ? (
          <button
            type="button"
            className="sk-menu-item"
            onClick={() => {
              close();
              control.onOpen();
            }}
          >
            {control.label}
          </button>
        ) : null}
        <MenuUpdateReminder />
        <MenuLicenseRow />
      </Menu>
    </div>
  );
}
