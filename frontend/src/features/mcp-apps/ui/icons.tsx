import type { ReactNode } from "react";

/**
 * The glyphs of the MCP Apps (designsystem §3 "Ikonknapp"): every glyph comes from this file, so there is one ⋯ and
 * one ›. Each is drawn on a 24 px box in currentColor. The icon button (family.css .sk-iconbtn) sizes it: a 44 px box,
 * the glyph in --sk-fg, or --sk-muted in a row. Decorative: the button's aria-label names the action.
 */

/** Three dots: `moreActions` in the room head and the ⋯ of a row. */
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

/** A magnifier: `search` in the room head. */
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

/** A pen: `edit`. */
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

/** A plus: the new-item control in a create row. */
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

/** A minus: the step down of an amount. */
export function MinusIcon() {
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
      <path d="M5 12h14" />
    </svg>
  );
}

/** A chevron pointing right: `open` and the next period. */
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

/** A chevron pointing left: the Back row's ‹ and the previous period. */
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

/** A landscape in a frame: a photo tile whose thumbnail is missing or could not be drawn (photos.tsx). */
export function PhotoIcon() {
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
      <rect x="3" y="5" width="18" height="14" rx="2" />
      <circle cx="9" cy="10" r="1.5" />
      <path d="M21 16l-5-5-8 8" />
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

/** The sizes a room glyph is drawn at: 20 in the room strip, 24 everywhere else. */
export type RoomIconProps = { size?: 20 | 24 };

/**
 * The outline shell of the glyphs below: a 24 box, a 2 px round stroke in currentColor, like the other outline glyphs.
 * `size` draws the same box smaller (the room strip's 20).
 */
function Outline({
  children,
  size = 24,
}: RoomIconProps & { children: ReactNode }) {
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
      {children}
    </svg>
  );
}

/** An arrow forward: the action row `moveAllOverdue` in the ring's column. */
export function ArrowRightIcon() {
  return (
    <Outline>
      <path d="M5 12h14M13 6l6 6-6 6" />
    </Outline>
  );
}

/** Pause: the action row `pause` in Sidekick's memory. */
export function PauseIcon() {
  return (
    <Outline>
      <path d="M9 6v12M15 6v12" />
    </Outline>
  );
}

/** Play: the action row `resume` while the memory is paused. */
export function PlayIcon() {
  return (
    <Outline>
      <path d="M8 5.5v13l10-6.5z" />
    </Outline>
  );
}

/** A clock: a wait ("Du väntar på Erik sedan 9 dagar") in the Contact's standing row. */
export function ClockIcon() {
  return (
    <Outline>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M12 7.5V12l3 2" />
    </Outline>
  );
}

/** A folder: `project` in a row's leading column. */
export function FolderIcon() {
  return (
    <Outline>
      <path d="M3 7a2 2 0 0 1 2-2h4l2 2h8a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z" />
    </Outline>
  );
}

/** Two arrows in a circle: `process` (work that goes on and never ends) in a row's leading column. */
export function CycleIcon() {
  return (
    <Outline>
      <path d="M20 12a8 8 0 0 1-13.7 5.6M4 12a8 8 0 0 1 13.7-5.6" />
      <path d="M18 3v4h-4M6 21v-4h4" />
    </Outline>
  );
}

/**
 * A loop of two arrows: a Task that repeats, before the rule in a row's meta line (the repeat text). Drawn at the
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

/*
 * The rooms' glyphs, for the room strip where the instance or the owner chose icons (nav-icons.ts). One family: calm
 * outline shapes on the 24 box that still read at the strip's 20, each a thing its room is about and none of them a
 * glyph an action already has (the strip's "more rooms" is four tiles, never the ⋯ of a room's tools).
 */

/** A house: the Start room. */
export function HouseIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <path d="M4 10.5 12 4l8 6.5V19a1 1 0 0 1-1 1h-4.5v-5.5h-5V20H5a1 1 0 0 1-1-1z" />
    </Outline>
  );
}

/** A ticked ring, the form of a Task that is done: the Work room. */
export function CheckRingIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <circle cx="12" cy="12" r="8.5" />
      <path d="M8.5 12.5l2.5 2.5 4.5-5.5" />
    </Outline>
  );
}

/** A bound notebook with two written lines: the Journal room. */
export function NotebookIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <rect x="5" y="3.5" width="14" height="17" rx="2" />
      <path d="M9 3.5v17M12.5 8.5h3M12.5 12h3" />
    </Outline>
  );
}

/** A basket with its handle: the Shopping room. */
export function BasketIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <path d="M3 10h18" />
      <path d="M4.5 10l1.4 8a1.5 1.5 0 0 0 1.5 1.25h9.2a1.5 1.5 0 0 0 1.5-1.25l1.4-8" />
      <path d="M8 10l3-5.5M16 10l-3-5.5" />
    </Outline>
  );
}

/** Two people: the Contacts room. */
export function PeopleIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <circle cx="9" cy="8.5" r="3.25" />
      <path d="M3 19.5a6 6 0 0 1 12 0" />
      <path d="M15.5 5.4a3.25 3.25 0 0 1 0 6.2" />
      <path d="M17.5 14a6 6 0 0 1 3.5 5.5" />
    </Outline>
  );
}

/** An open book: the Library room. */
export function OpenBookIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <path d="M12 7v13" />
      <path d="M12 7C10.5 5.5 8 5 4 5v13c4 0 6.5.5 8 2 1.5-1.5 4-2 8-2V5c-4 0-6.5.5-8 2z" />
    </Outline>
  );
}

/** A bolt: the Automations room. */
export function BoltIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <path d="M13 3 5 13.5h6.5L10.5 21 19 10.5h-6.5z" />
    </Outline>
  );
}

/** Four tiles: the strip's last cell, the rooms that have no cell of their own. */
export function TilesIcon({ size }: RoomIconProps) {
  return (
    <Outline size={size}>
      <rect x="4" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="4" width="6.5" height="6.5" rx="1.5" />
      <rect x="4" y="13.5" width="6.5" height="6.5" rx="1.5" />
      <rect x="13.5" y="13.5" width="6.5" height="6.5" rx="1.5" />
    </Outline>
  );
}
