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
 * The bar above the rooms: the room strip (or the narrow room picker), the Back row with `collapse`, and the
 * question about unsaved edits. Nothing here navigates by itself; every press goes to the shell.
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
  back,
  collapse,
  ask,
}: {
  labels: SidekickShellLabels;
  barRef: Ref<HTMLDivElement>;
  tabsRef: Ref<HTMLDivElement>;
  /** False when the strip is not drawn (a host with one room, or one that cannot navigate). */
  strip: boolean;
  stripRooms: readonly RoomId[];
  stripCurrent: RoomId | undefined;
  tabStop: RoomId | undefined;
  narrow: boolean;
  onChoose: (room: RoomId) => void;
  picker: { button: ReactNode; menu: ReactNode };
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
                aria-current={room === stripCurrent ? "page" : undefined}
                tabIndex={room === tabStop ? 0 : -1}
                onClick={() => onChoose(room)}
              >
                {labels.rooms[room]}
              </button>
            ))}
          </KeyScope>
          {picker.button}
        </nav>
      ) : null}
      {picker.menu}
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
