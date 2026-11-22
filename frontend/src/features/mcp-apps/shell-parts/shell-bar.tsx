import type { ReactNode, Ref } from "react";

import type { RoomId } from "@/features/mcp-apps/router";
import type { SidekickShellLabels } from "@/features/mcp-apps/sidekick-shell-labels";
import { UnsavedAsk } from "@/features/mcp-apps/unsaved-guard";
import { BackHeader } from "@/features/mcp-apps/ui/back-header";
import { KeyScope } from "@/features/mcp-apps/ui/key-scope";

/** The unsaved-edits question: shown under the bar while it is open for the layer on top. */
export type ShellAsk = {
  onDiscard: () => void;
  onKeep: () => void;
  keepRef: (element: HTMLButtonElement | null) => void;
};

/**
 * The bar above the rooms: the room strip (its rooms and the Mer cell, or the narrow room picker), in a wide frame the room's head beside it on
 * the same row, the Back row with `collapse`, and the question about unsaved edits. Nothing here navigates by itself; every press goes to the shell.
 */
export function ShellBar({
  labels,
  barRef,
  tabsRef,
  strip,
  stripRooms,
  stripCurrent,
  tabStop,
  narrow,
  onChoose,
  picker,
  more,
  back,
  collapse,
  ask,
  headSlotRef,
}: {
  labels: SidekickShellLabels;
  barRef: Ref<HTMLDivElement>;
  tabsRef: Ref<HTMLDivElement>;
  /** False when the strip is not drawn (a host with one room, or one that cannot navigate). */
  strip: boolean;
  /** The rooms with a cell of their own; the rooms of Mer are in `more`. */
  stripRooms: readonly RoomId[];
  stripCurrent: RoomId | undefined;
  /** The room cell that is the strip's one tab stop; undefined when it is the Mer cell. */
  tabStop: RoomId | undefined;
  narrow: boolean;
  onChoose: (room: RoomId) => void;
  picker: { button: ReactNode; menu: ReactNode };
  /** The Mer cell, last in the row, and its menu (strip-more.tsx); both null when Mer has no room. */
  more: { cell: ReactNode; menu: ReactNode };
  /** The Back row: where it leads, what it does and where the layer on top puts its own actions. Absent: no Back. */
  back?: {
    label: string;
    onBack: () => void;
    slotRef: (element: HTMLSpanElement | null) => void;
  };
  /** Fäll ihop, when the full view is only our own expansion. */
  collapse?: { label: string; onCollapse: () => void };
  /** The question about unsaved edits, while it is open for the layer on top. */
  ask?: ShellAsk;
  /** A wide frame: the place after the strip where the room on top draws its head (ui/room-head.tsx), one row. */
  headSlotRef?: (element: HTMLDivElement | null) => void;
}) {
  const collapseButton = collapse ? (
    <button
      type="button"
      className="sk-rooms__collapse"
      onClick={collapse.onCollapse}
    >
      {collapse.label}
    </button>
  ) : undefined;
  return (
    <div className="sk-rooms__bar" ref={barRef}>
      {strip ? (
        <nav className="sk-rooms" aria-label={labels.stripLabel}>
          <KeyScope
            roving
            ref={tabsRef}
            className="sk-rooms__tabs"
            data-narrow={narrow || undefined}
          >
            {stripRooms.map((room) => (
              <button
                key={room}
                type="button"
                className="sk-rooms__tab"
                data-label={labels.rooms[room]}
                aria-current={room === stripCurrent ? "page" : undefined}
                tabIndex={room === tabStop ? 0 : -1}
                onClick={() => onChoose(room)}
              >
                {labels.rooms[room]}
              </button>
            ))}
            {more.cell}
          </KeyScope>
          {picker.button}
        </nav>
      ) : null}
      {headSlotRef ? (
        <div className="sk-rooms__head" ref={headSlotRef} />
      ) : null}
      {picker.menu}
      {more.menu}
      {back ? (
        <BackHeader
          // "‹ X" names where it leads, also in Control (the room's name over the `control` title).
          label={back.label}
          onBack={back.onBack}
          actions={collapseButton}
          slotRef={back.slotRef}
        />
      ) : collapseButton ? (
        <div className="sk-rooms__row">{collapseButton}</div>
      ) : null}
      {ask ? (
        <UnsavedAsk
          labels={labels}
          onDiscard={ask.onDiscard}
          onKeep={ask.onKeep}
          keepRef={ask.keepRef}
        />
      ) : null}
    </div>
  );
}
