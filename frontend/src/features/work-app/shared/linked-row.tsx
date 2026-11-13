import { useEffect, useRef, useState, type ReactNode } from "react";
import type { WorkLabels } from "./labels";
import { linksLabelsFor } from "./links-labels";
import { manageLabelsFor } from "./manage-labels";
import {
  RowMenuButton,
  RowMenuTip,
  rowMenuHandlers,
  rowMenuHint,
} from "./row-menu";

/** The tip's and the hint's words: the Task row's, with this list's "a row" in place of "a task". */
function rowLabels(t: WorkLabels): WorkLabels {
  const links = linksLabelsFor(t.dateLocale);
  return {
    ...t,
    rowMenuHint: links.rowMenuHint,
    rowMenuKeys: links.rowMenuKeys,
  };
}

/** The `aria-description` of a linked row's title button: how to open its menu with this input. */
export const linkedRowHint = (t: WorkLabels) => rowMenuHint(rowLabels(t));

/** The long-press tip under a list of linked rows, until the quick choices are first opened anywhere. */
export function LinkedRowTip({ labels: t }: { labels: WorkLabels }) {
  return <RowMenuTip labels={rowLabels(t)} />;
}

/**
 * A linked row (a Contact under a Task, a Project under a Contact) with its own quick menu (design system §3 "Snabbval",
 * as Work's rows and Steps): a long press (touch), a right click, Shift+F10 or the menu key opens "Ta bort koppling",
 * and a button drawn nowhere ("Fler val för {namn}") opens the same menu for a screen reader. There is no ⋯ on the row;
 * a plain tap still opens what the row links to. The menu writes at once; the row then stays with its Ångra (`gone`) and
 * the focus goes to it. Without `onRemove` the row has no menu. `children` are the row's `work-agenda-line`.
 */
export function LinkedRow({
  title,
  gone,
  busy,
  onRemove,
  labels: t,
  children,
}: {
  /** The row's name, for the hidden menu button's label. */
  title: string;
  /** The link was removed and Ångra is offered: the menu is closed and gone. */
  gone: boolean;
  busy: boolean;
  /** Removes the link. Absent: the host cannot remove it, and the row has no menu. */
  onRemove?: () => void;
  labels: WorkLabels;
  children: ReactNode;
}) {
  const [open, setOpen] = useState(false);
  const row = useRef<HTMLLIElement>(null);
  // Set by "Ta bort koppling": once Ångra stands in the row, the focus goes to it (the focus rule of every unlink).
  const refocus = useRef(false);
  const hasMenu = Boolean(onRemove) && !gone;
  useEffect(() => {
    if (!gone || !refocus.current) return;
    refocus.current = false;
    row.current
      ?.querySelector<HTMLElement>("button.sk-btn--secondary")
      ?.focus();
  }, [gone]);
  return (
    <li
      ref={row}
      className="work-agenda-row work-open-row"
      data-gone={gone ? "gone" : undefined}
      {...(hasMenu ? rowMenuHandlers(open, setOpen) : {})}
    >
      {children}
      {hasMenu && open && (
        <div className="work-contact-menu work-linked-row-menu">
          <button
            type="button"
            className="work-contact-menu-item"
            data-danger
            disabled={busy}
            onClick={() => {
              refocus.current = true;
              setOpen(false);
              onRemove?.();
            }}
          >
            {manageLabelsFor(t.dateLocale).removeLink}
          </button>
        </div>
      )}
      {hasMenu && (
        <RowMenuButton
          label={t.rowMenuButton(title)}
          open={() => setOpen(true)}
          firstChoice=".work-linked-row-menu button:not(:disabled)"
        />
      )}
    </li>
  );
}
