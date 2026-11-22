import { useContext, type ReactNode, type Ref } from "react";
import { createPortal } from "react-dom";

import { MoreIcon, PlusIcon, SearchIcon } from "./icons";
import { RoomSurfaceContext } from "./room-context";
import { useRoomShortcuts } from "./shortcut-registry";
import "./room-head.css";

/** One of the head's own tools: search or +. */
export type RoomHeadButton = {
  /** Accessible name and tooltip, in the caller's language ("Ny uppgift"); the tooltip adds the key ("Ny uppgift (N)"). */
  label: string;
  onPress: () => void;
  /** What the key does when it differs from a press: "/" opens the search field and puts the focus in it, never closes it. */
  onKey?: () => void;
  /** aria-expanded, for a button that unfolds a field or a panel under the head. */
  expanded?: boolean;
  controls?: string;
  /** While the list loads or could not be read: aria-disabled in the tertiary tone, and a press or the key does nothing. */
  disabled?: boolean;
};

/** A view the keys reach: `g` and its letter (the view id's, the same in both languages). */
export type RoomHeadView = { key: string; label: string; onChoose: () => void };

export type RoomHeadProps = {
  /** The room's root class ("sidekick-work"): the head keeps it around itself in the shell's row, so the room's own rules still reach what it holds. */
  scope: string;
  /** The view switch (`Tabs` or Work's `ViewTabs`). */
  tabs?: ReactNode;
  /** The views of `tabs` for the keys: `g a` Agenda, `g s` Status … (desktop spec 2.6). */
  views?: readonly RoomHeadView[];
  /** Something before the tools that is not a tool ("Idag" in an older week). */
  extra?: ReactNode;
  /** The search icon; binds "/". */
  search?: RoomHeadButton;
  /** The round +; binds "n". */
  add?: RoomHeadButton;
  /** The search and + buttons themselves, for a caller that gives the focus back to them. */
  searchRef?: Ref<HTMLButtonElement>;
  addRef?: Ref<HTMLButtonElement>;
  /** The room's ⋯ (built on ui/menu), always outermost. */
  more?: ReactNode;
  /**
   * False: the head has no tools of its own (Control). In place it is then only its tabs, as before; in the shell's
   * row it keeps the three empty boxes, so nothing moves between the rooms.
   */
  tools?: boolean;
  /** The name of the group the head's keys are listed under in the keyboard help: the room's name. */
  keysTitle: string;
  /** A class of the room's own on the row (Work's `sk-shell-tabs`, which its board rule and the measurements read). */
  className?: string;
};

/** An empty tool box: the place of a tool this view does not offer, so the others never move. */
function Slot() {
  return <span className="sk-room-head__slot" aria-hidden="true" />;
}

function HeadButton({
  label,
  onPress,
  expanded,
  controls,
  disabled,
  buttonRef,
  shortcut,
  primary,
  children,
}: Omit<RoomHeadButton, "onKey"> & {
  buttonRef?: Ref<HTMLButtonElement>;
  shortcut: string;
  primary?: boolean;
  children: ReactNode;
}) {
  return (
    <button
      ref={buttonRef}
      type="button"
      className={
        primary
          ? "sk-iconbtn sk-iconbtn--primary sk-room-head__tool sk-room-head__add"
          : "sk-iconbtn sk-room-head__tool"
      }
      aria-label={label}
      title={`${label} (${shortcut.toUpperCase()})`}
      aria-keyshortcuts={shortcut}
      aria-expanded={expanded}
      aria-controls={controls}
      aria-disabled={disabled || undefined}
      onClick={() => {
        if (!disabled) onPress();
      }}
    >
      {children}
    </button>
  );
}

/**
 * The room header (designsystem §3 "Rumshuvud", desktop spec 2.2): the room's view tabs, then its tools at fixed
 * places, counted from the right: ⋯ outermost, + and search, 44 boxes 4 apart, and an empty box where a view has no
 * such tool, so + has the same middle in every room and view.
 *
 * In a wide frame the shell offers a place in its own row (`headSlot`, sidekick-shell.tsx): the head is drawn there,
 * after the room strip, and the shell's head is one row. Without that place (below 64rem, a host with one room, the
 * reserve strip, an inline card) it is drawn where it stands, as the room's own sticky row under the strip.
 *
 * "/" presses search, "n" presses + and `g` with a view's letter shows the view, on the layer on top only
 * (useShortcuts), never in a field; all are listed in the keyboard help under the room's name.
 */
export function RoomHead({
  scope,
  tabs,
  views = [],
  extra,
  search,
  add,
  searchRef,
  addRef,
  more,
  tools = true,
  keysTitle,
  className,
}: RoomHeadProps) {
  const { headSlot } = useContext(RoomSurfaceContext);
  const keys: Record<string, () => void> = {};
  const keyLabels: Record<string, string> = {};
  for (const view of views) {
    keys[`g ${view.key}`] = view.onChoose;
    keyLabels[`g ${view.key}`] = view.label;
  }
  if (search) {
    keys["/"] = () => {
      if (!search.disabled) (search.onKey ?? search.onPress)();
    };
    keyLabels["/"] = search.label;
  }
  if (add) {
    keys.n = () => {
      if (!add.disabled) (add.onKey ?? add.onPress)();
    };
    keyLabels.n = add.label;
  }
  useRoomShortcuts(keys, {
    id: "room-head",
    title: keysTitle,
    labels: keyLabels,
  });

  const inBar = Boolean(headSlot);
  if (!tools && !inBar) return <>{tabs}</>;
  const row = (
    <div
      className={className ? `sk-room-head ${className}` : "sk-room-head"}
      data-place={inBar ? "bar" : "room"}
    >
      <div className="sk-room-head__tabs">{tabs}</div>
      {extra}
      {search ? (
        <HeadButton
          label={search.label}
          onPress={search.onPress}
          expanded={search.expanded}
          controls={search.controls}
          disabled={search.disabled}
          buttonRef={searchRef}
          shortcut="/"
        >
          <SearchIcon />
        </HeadButton>
      ) : (
        <Slot />
      )}
      {add ? (
        <HeadButton
          label={add.label}
          onPress={add.onPress}
          expanded={add.expanded}
          controls={add.controls}
          disabled={add.disabled}
          buttonRef={addRef}
          shortcut="n"
          primary
        >
          <PlusIcon />
        </HeadButton>
      ) : (
        <Slot />
      )}
      {more ?? <Slot />}
    </div>
  );
  return headSlot
    ? createPortal(
        <div className={`${scope} sk-room-head-scope`}>{row}</div>,
        headSlot,
      )
    : row;
}

/** A ⋯ drawn while nothing can open it yet (the Work list before its first read): the same box, in place. */
export function RoomHeadMoreGlyph() {
  return (
    <span className="sk-iconbtn sk-room-head__tool">
      <MoreIcon />
    </span>
  );
}
