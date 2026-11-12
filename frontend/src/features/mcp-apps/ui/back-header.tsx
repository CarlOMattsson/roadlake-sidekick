import { useContext, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";

import { appLocale } from "../app-locale";
import { sidekickShellLabelsFor } from "../sidekick-shell-labels";
import { ChevronLeftIcon } from "./icons";
import { RoomSurfaceContext } from "./room-context";

import "./back-header.css";

/**
 * The Back row of a view one step below its parent (designsystem §3, Tillbakarad): a text button "‹ {label}"
 * back to the parent on the left, and the view's actions on the right in the order pen, ⋯ (⋯ outermost), in one
 * row 44 px high. An optional title sits right under that row as the view's heading (--sk-type-title). The Back
 * has no frame and its chevron starts exactly on the content edge. The text after ‹ always names where it leads
 *, and its accessible name is "Tillbaka till {label}" ("Back to {label}" in English). Actions are icon
 * buttons: no frame, 44x44, a 24 px glyph in --sk-fg.
 *
 * Shared by the shell and the rooms, so every Back looks and sits the same way. The shell's Back row also holds
 * a slot (`slotRef`) at the outer end of the actions, where the view on top puts its own pen and ⋯ with
 * `BackHeaderActions`.
 */
export function BackHeader({
  label,
  onBack,
  title,
  actions,
  slotRef,
}: {
  /** The parent's name, for example "Status", "Kontakter" or "Listor". It is part of the button's accessible name. */
  label: string;
  onBack: () => void;
  /** Shown under the Back row, as the view's heading. */
  title?: string;
  actions?: ReactNode;
  /** The element the view on top portals its actions into (sidekick-shell). */
  slotRef?: Ref<HTMLSpanElement>;
}) {
  const name = sidekickShellLabelsFor(appLocale()).backTo(label);
  return (
    <div className="sk-back-header">
      <div className="sk-back-header__bar">
        <button
          type="button"
          className="sk-back-header__back"
          aria-label={name}
          onClick={onBack}
        >
          <ChevronLeftIcon />
          <span className="sk-back-header__label">{label}</span>
        </button>
        {actions || slotRef ? (
          <div className="sk-back-header__actions">
            {actions}
            {slotRef ? (
              <span ref={slotRef} className="sk-back-header__slot" />
            ) : null}
          </div>
        ) : null}
      </div>
      {title ? <h2 className="sk-back-header__title">{title}</h2> : null}
    </div>
  );
}

/**
 * Puts a view's actions (pen, ⋯) at the end of the shell's Back row, while the view is on top and the shell
 * draws a Back. Renders nothing otherwise: check `useBackHeaderSlot()` and draw them in the view then.
 * Give each action the class `sk-iconbtn` and an aria-label.
 */
export function BackHeaderActions({ children }: { children: ReactNode }) {
  const { backActions } = useContext(RoomSurfaceContext);
  return backActions ? createPortal(children, backActions) : null;
}

/** True when the shell's Back row has room for this view's actions (see BackHeaderActions). */
export function useBackHeaderSlot(): boolean {
  return Boolean(useContext(RoomSurfaceContext).backActions);
}
