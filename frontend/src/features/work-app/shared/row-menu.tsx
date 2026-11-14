import type { KeyboardEvent, MouseEvent } from "react";
import { flushSync } from "react-dom";
import { CloseIcon } from "../../mcp-apps/ui/icons";
import { finePointer } from "../../mcp-apps/ui/shortcuts";
import type { WorkLabels } from "./labels";

/**
 * The keys and the long press that open a row's quick choices (designsystem §3 "Snabbval"): `contextmenu` (a
 * long press on touch, a right click), Shift+F10 and the menu key toggle them, and Escape closes them. A context menu
 * the drag handle already took (it prevents the default) is left alone.
 */
export function rowMenuHandlers(open: boolean, set: (open: boolean) => void) {
  return {
    onContextMenu(event: MouseEvent) {
      if (event.defaultPrevented) return;
      event.preventDefault();
      menuUsed();
      forgetMenuButton(event.currentTarget as HTMLElement);
      set(!open);
    },
    onKeyDown(event: KeyboardEvent) {
      // A menu inside this row (an Action under a Step) handled the key first.
      if (event.defaultPrevented) return;
      const menu =
        event.key === "ContextMenu" || (event.shiftKey && event.key === "F10");
      if (!menu && !(open && event.key === "Escape")) return;
      event.preventDefault();
      const row = event.currentTarget as HTMLElement;
      if (menu) {
        menuUsed();
        forgetMenuButton(row);
      }
      // Escape from inside the menu: the focused choice unmounts, so the control that opened it (the hidden menu button,
      // when that opened it) or else the row's own control takes the focus back.
      else
        (
          menuButtonOf(row) ?? row.querySelector<HTMLElement>("input, button")
        )?.focus();
      set(menu && !open);
    },
  };
}

/** The attribute that marks the hidden menu button which opened its row's menu, so closing can return to it. */
const OPENED_BY_BUTTON = "data-row-menu-via";

/** The row's hidden menu button, if it is the one that opened the menu now open (or last opened). */
export function menuButtonOf(row: Element | null | undefined) {
  // Direct children only: an Action's menu button inside a Step's row is not the Step's.
  return (
    row?.querySelector<HTMLElement>(`:scope > [${OPENED_BY_BUTTON}]`) ??
    undefined
  );
}

function forgetMenuButton(row: Element) {
  row
    .querySelector(`:scope > [${OPENED_BY_BUTTON}]`)
    ?.removeAttribute(OPENED_BY_BUTTON);
}

/**
 * The × at the end of a Step's or an Action's menu: it closes the menu and sends the focus where Escape does (the hidden
 * menu button that opened it, else the row's own control), since the button unmounts with the menu.
 */
export function RowMenuClose({
  label,
  close,
}: {
  label: string;
  close: () => void;
}) {
  return (
    <button
      type="button"
      className="sk-iconbtn work-step-menu-close"
      aria-label={label}
      onClick={(event) => {
        const row = event.currentTarget.closest("li");
        (
          menuButtonOf(row) ?? row?.querySelector<HTMLElement>("input, button")
        )?.focus();
        close();
      }}
    >
      <CloseIcon />
    </button>
  );
}

/**
 * The row's menu for a screen reader (designsystem §3 "Snabbval"): a button drawn nowhere (`work-visually-hidden`),
 * last in the row, that opens the same menu as the long press and puts the focus on the menu's first choice. It is out
 * of the Tab order (the keyboard has Shift+F10); Escape or the close button in the menu returns the focus to it.
 * `open` opens the menu, `firstChoice` finds its first choice inside the row.
 */
export function RowMenuButton({
  label,
  open,
  firstChoice,
}: {
  label: string;
  open: () => void;
  firstChoice: string;
}) {
  return (
    <button
      type="button"
      className="work-visually-hidden"
      tabIndex={-1}
      onClick={(event) => {
        const button = event.currentTarget;
        const row = button.closest("li");
        menuUsed();
        button.setAttribute(OPENED_BY_BUTTON, "1");
        // The menu stands in the DOM before the focus goes to its first choice.
        flushSync(open);
        row?.querySelector<HTMLElement>(firstChoice)?.focus();
      }}
    >
      {label}
    </button>
  );
}

/*
 * The long-press tip (designsystem §3 "Listrad"): `rowMenuHint` stands last in Agenda and
 * Status until the quick choices are first opened, and is gone for good after that. The frame's storage keeps it when
 * the host allows it; the document's `data-row-menu` keeps it for the session when not, and hides a tip that is still
 * drawn (agenda.css) until its list draws again.
 */
const TIP_KEY = "sidekick.rowMenuUsed";
const seen = document.documentElement.dataset;
function menuUsed() {
  seen.rowMenu = "1";
  try {
    localStorage[TIP_KEY] = "1";
  } catch {
    // No storage in this frame: the document keeps the answer for the session.
  }
}

/**
 * The row hint: the long press on touch, the right click and Shift+F10 with a fine pointer. `step` gives the
 * Step's words.
 */
export const rowMenuHint = (t: WorkLabels, step?: boolean) =>
  finePointer()
    ? step
      ? t.stepMenuKeys
      : t.rowMenuKeys
    : step
      ? t.stepMenuHint
      : t.rowMenuHint;

/**
 * The long-press tip, last in a list of Tasks (or under a Task's Steps, `step`), until the quick choices are first
 * opened. One answer for both: a long press learnt on a row is known on a Step. A view with several lists (the Task's
 * Steps and Contacts, a Contact's Projects) shows one tip, the last one in the article, so the same sentence is not
 * repeated down the page: each tip hides itself while another stands after it, and shows again when that one leaves.
 */
export function RowMenuTip({
  labels: t,
  step,
}: {
  labels: WorkLabels;
  step?: boolean;
}) {
  let used = seen.rowMenu;
  try {
    used ||= localStorage[TIP_KEY];
  } catch {
    // No storage: only this session's answer counts.
  }
  if (used) return null;
  return (
    <p
      className="work-row-tip"
      ref={(tip) => {
        const scope: ParentNode = tip?.closest("article") ?? document;
        /** Hides every tip of the scope but the last; `leaving` is a tip that is going and no longer counts. */
        const settle = (leaving?: HTMLElement) => {
          const tips = [
            ...scope.querySelectorAll<HTMLElement>(".work-row-tip"),
          ].filter((other) => other !== leaving);
          tips.forEach((other, index) => {
            other.hidden = index < tips.length - 1;
          });
        };
        settle();
        return () => settle(tip ?? undefined);
      }}
    >
      {rowMenuHint(t, step)}
    </p>
  );
}
