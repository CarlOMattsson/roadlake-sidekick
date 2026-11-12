import { useEffect, useId, useRef, type ReactNode, type Ref } from "react";
import { CloseIcon, MoreIcon, SearchIcon } from "./agenda-icons";
import { PlusIcon } from "../mcp-apps/ui/icons";
import { MenuUpdateReminder, useMoreMark } from "../mcp-apps/update-reminder";
import { MenuLicenseRow, useLicenseMenu } from "../mcp-apps/license-mark";
import type { WorkLabels } from "./labels";
import "./agenda-toolbar.css";

/**
 * The search icon of the agenda, at the end of the tab row (the shell's tabsEnd), left of "⋯" (designsystem §3
 * "Rumshuvud": counted from the right, ⋯ then search). It unfolds the search field under the tab row; the caller owns
 * whether it is open and gives the field's id, so the button names what it controls.
 */
export function AgendaSearchToggle({
  label,
  open,
  disabled,
  controls,
  onOpenChange,
  buttonRef,
}: {
  /** "Sök uppgifter" / "Search tasks". */
  label: string;
  open: boolean;
  /** True while the list loads or could not be read: aria-disabled (tertiary), and a tap does nothing. */
  disabled?: boolean;
  /** The id of the search field's row. */
  controls: string;
  onOpenChange: (open: boolean) => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="sk-iconbtn work-tab-tool"
      aria-label={label}
      aria-expanded={open}
      aria-controls={controls}
      aria-disabled={disabled || undefined}
      onClick={() => {
        if (!disabled) onOpenChange(!open);
      }}
    >
      <SearchIcon />
    </button>
  );
}

/**
 * + in the tab row, between search and "⋯" (designsystem §3 "Skapa"): it unfolds the new-Task field under the row.
 * While the list loads or could not be read it is aria-disabled (tertiary) and a tap does nothing.
 */
export function CreateToggle({
  label,
  open,
  disabled,
  controls,
  onOpenChange,
  buttonRef,
}: {
  /** "Ny uppgift" / "New task". */
  label: string;
  open: boolean;
  disabled: boolean;
  controls: string;
  onOpenChange: (open: boolean) => void;
  buttonRef?: Ref<HTMLButtonElement>;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className="sk-iconbtn sk-iconbtn--primary work-tab-tool work-tab-create"
      aria-label={label}
      aria-expanded={open}
      aria-controls={controls}
      aria-disabled={disabled || undefined}
      onClick={() => {
        if (!disabled) onOpenChange(!open);
      }}
    >
      <PlusIcon />
    </button>
  );
}

/**
 * The search field of the fullscreen agenda, unfolded under the tab row by the search icon (designsystem §3
 * "Skapa": a screen shows at most one text field, so the new-Task field closes while this one is open). It is 48 px
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
  /** Name and placeholder of the field: "Sök uppgifter" / "Search tasks". */
  label: string;
  /** Name of the ×: "Stäng sökningen" / "Close search". */
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
 * The "⋯" button of a Work tab, at the end of the tab row (the shell's tabsEnd). It unfolds a menu with the view's
 * rarer actions (Sparade vyer, Uppdatera, and "Kontroll" last, designsystem §3 "Rumshuvud") under the tab row, at full width, in the page flow; the button
 * stays where it is. The caller owns the state (open or closed), because the view under it is remounted when a saved
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
   * The last item: "Kontroll", which opens the Control room, or the host's own settings in its place (the phone's
   * "Inställningar"). Absent when the host has neither. The focus returns to ⋯ before it opens, so a screen that closes
   * again can give it back there.
   */
  control?: { label: string; onOpen: () => void };
  /** The first item of the menu: the saved views bar. */
  children?: ReactNode;
}) {
  const panelId = useId();
  const more = useRef<HTMLButtonElement>(null);
  const mark = useMoreMark(t.moreActions);
  // The license coin asks (Kontroll off): the ⋯ of the tab on screen opens on its row.
  useLicenseMenu(more, () => onOpenChange(true));
  function close() {
    onOpenChange(false);
    more.current?.focus();
  }
  return (
    <div className="work-agenda-more" hidden={hidden}>
      <button
        ref={more}
        type="button"
        className="sk-iconbtn work-tab-tool work-agenda-bar-more"
        aria-label={mark.label}
        aria-expanded={open}
        aria-controls={panelId}
        onClick={() => onOpenChange(!open)}
      >
        <MoreIcon />
        {mark.dot}
      </button>
      {/* eslint-disable-next-line jsx-a11y/no-static-element-interactions -- a container-level handler for keys bubbling up from the focusable controls inside it (Escape closes); the container itself is not a control. */}
      <div
        id={panelId}
        className="work-agenda-bar-panel"
        hidden={!open}
        onKeyDown={(event) => {
          if (event.key === "Escape") {
            event.stopPropagation();
            close();
          }
        }}
      >
        {children}
        <button
          type="button"
          className="work-agenda-bar-refresh"
          onClick={() => {
            onRefresh();
            close();
          }}
        >
          {t.refresh}
        </button>
        {control ? (
          <button
            type="button"
            className="work-agenda-bar-refresh"
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
      </div>
    </div>
  );
}
