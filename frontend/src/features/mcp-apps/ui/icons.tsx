import type { ReactNode } from "react";

/**
 * The glyphs of the MCP Apps (designsystem §3 "Ikonknapp"): every glyph comes from this file, so there is one ⋯ and
 * one ›. Each is drawn on a 24 px box in currentColor. The icon button (family.css .sk-iconbtn) sizes it: a 44 px box,
 * the glyph in --sk-fg, or --sk-muted in a row. Decorative: the button's aria-label names the action.
 */

/** Three dots: "Fler alternativ" in the room head and the ⋯ of a row. */
export function MoreIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="currentColor"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="5" cy="12" r="2" />
      <circle cx="12" cy="12" r="2" />
      <circle cx="19" cy="12" r="2" />
    </svg>
  );
}

/** A magnifier: "Sök uppgifter" in the room head. */
export function SearchIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <circle cx="10.5" cy="10.5" r="6.5" />
      <path d="M15.5 15.5 20 20" />
    </svg>
  );
}

/** A cross: closes a search field. */
export function CloseIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M6 6l12 12M18 6 6 18" />
    </svg>
  );
}

/** A pen: "Redigera". */
export function PenIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 20h9" />
      <path d="M16.5 3.5a2.1 2.1 0 0 1 3 3L7 19l-4 1 1-4Z" />
    </svg>
  );
}

/** A plus: "Ny" in a create row. */
export function PlusIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M12 5v14M5 12h14" />
    </svg>
  );
}

/** A chevron pointing right: "Öppna" and the next period. */
export function ChevronRightIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M9 6l6 6-6 6" />
    </svg>
  );
}

/** A chevron pointing left: "‹ Förälder" and the previous period. */
export function ChevronLeftIcon() {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M15 6l-6 6 6 6" />
    </svg>
  );
}

/** A chevron pointing down: the ⌄ of a property chip and a collapsible heading. 16 or 24 px. */
export function ChevronDownIcon({ size = 24 }: { size?: 16 | 24 }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width={size}
      height={size}
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M6 9l6 6 6-6" />
    </svg>
  );
}

/** The outline shell of the row glyphs below: 24 px, a 2 px round stroke in currentColor, like the other outline glyphs. */
function Outline({ children }: { children: ReactNode }) {
  return (
    <svg
      viewBox="0 0 24 24"
      width="24"
      height="24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      {children}
    </svg>
  );
}

/** An arrow forward: the action row "Flytta N försenade till imorgon" in the ring's column. */
export function ArrowRightIcon() {
  return (
    <Outline>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Outline>
  );
}

/** Pause: the action row "Pausa minnet" in Sidekick's memory. */
export function PauseIcon() {
  return (
    <Outline>
      <path d="M9 6v12M15 6v12" />
    </Outline>
  );
}

/** Play: the action row "Återuppta minnet" while the memory is paused. */
export function PlayIcon() {
  return (
    <Outline>
      <path d="M8 5.5v13l10-6.5z" />
    </Outline>
  );
}

/** A folder: "Projekt" in a row's leading column. */
export function FolderIcon() {
  return (
    <Outline>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Outline>
  );
}

/** Two arrows in a circle: "Process" (work that goes on and never ends) in a row's leading column. */
export function CycleIcon() {
  return (
    <Outline>
      <path d="M20 12a8 8 0 0 1-13.7 5.6M4 12a8 8 0 0 1 13.7-5.6" />
      <path d="M18 3v4h-4M6 21v-4h4" />
    </Outline>
  );
}

/**
 * A loop of two arrows: a Task that repeats, before the rule in a row's meta line ("↻ varje månad"). Drawn at the
 * meta's text size; the words beside it carry the meaning, so it is hidden from screen readers.
 */
export function RepeatIcon() {
  return (
    <svg
      className="sk-repeat-icon"
      viewBox="0 0 24 24"
      width="14"
      height="14"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.25"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
      focusable="false"
    >
      <path d="M17 2l4 4-4 4" />
      <path d="M3 11v-1a4 4 0 0 1 4-4h14" />
      <path d="M7 22l-4-4 4-4" />
      <path d="M21 13v1a4 4 0 0 1-4 4H3" />
    </svg>
  );
}
