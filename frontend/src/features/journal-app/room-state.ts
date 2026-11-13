import type { EntryCardData } from "./entry-card";
import { cardFrom } from "./room-card";
import { rootFromToolResult, type JournalFrame } from "./transport";
import { toolResultCause } from "../mcp-apps/ui/states";
import type { RoomProps } from "../mcp-apps/room-types";

/**
 * What the room holds. The fields up to `received` say which result this state was derived from: a
 * changed resultId, initial or initialError is a new result, and the state is derived again from the
 * previous one (during render, as JournalView does with its `initial`).
 */
export type RoomState = {
  seenId?: number;
  seenInitial?: unknown;
  seenError?: boolean;
  /** Until the first tool result of this room. A result that is an error only fails the room as the first one. */
  received: boolean;
  /** The root the view shows; absent until a result names one, when the view reads today itself. */
  frame?: JournalFrame;
  /**
   * Set while a single entry result is shown as the compact card. "Open" clears it and shows the
   * existing entry view for that entry, so the card itself never reads the entry again.
   */
  card?: EntryCardData;
  /**
   * Counts the single-entry results that showed a card. The card is keyed by it, so a new result starts
   * with the summary again, while a link change on the same card keeps what the owner is reading.
   */
  cardResults: number;
  /** Set when the first tool result is an error: the shared error notice shows until Retry. */
  failed: boolean;
  /** What the last failed read threw, so the notice adds "Check your connection" only when it may be that. */
  cause?: unknown;
  /** Set while Retry reads today again, so a second press does not start another read. */
  retrying: boolean;
  /** Set while Open waits for the host's answer to a fullscreen request, so a second press waits too. */
  opening: boolean;
  /**
   * Set when the host refuses or fails the fullscreen request of the day glance, or offers none: the
   * day then shows inline in the glance's place, as the fallback. A new root clears it.
   */
  dayInline: boolean;
  /** Set while the day glance's Open waits for the host's answer, so a second press waits too. */
  dayOpening: boolean;
  /** The count of drafts awaiting review on one day, kept only for the glance; a new root clears it. */
  drafts?: { date: string; count: number };
};

const NO_RESULT: RoomState = {
  received: false,
  cardResults: 0,
  failed: false,
  retrying: false,
  opening: false,
  dayInline: false,
  dayOpening: false,
};

export function resultChanged(state: RoomState, props: RoomProps): boolean {
  return (
    props.resultId !== state.seenId ||
    props.initial !== state.seenInitial ||
    props.initialError !== state.seenError
  );
}

/** A new root replaces the view; the card, its notices, the inline day and the draft count start again. */
export function withRoot(prev: RoomState, frame: JournalFrame): RoomState {
  return {
    ...prev,
    frame,
    card: undefined,
    dayInline: false,
    drafts: undefined,
  };
}

/** Shows the existing entry view for one entry, replacing the card. */
export function withEntry(prev: RoomState, id: string): RoomState {
  return {
    ...prev,
    frame: { kind: "entry", id },
    card: undefined,
  };
}

/**
 * The state after a tool result. Every tool result that opens the room re-roots it; anything else is
 * ignored. An error result keeps the view that is shown; an error before any view shows the error notice.
 */
export function applyResult(prev: RoomState, props: RoomProps): RoomState {
  const base: RoomState = {
    ...prev,
    seenId: props.resultId,
    seenInitial: props.initial,
    seenError: props.initialError,
    received: true,
  };
  if (props.initialError === true) {
    return prev.received
      ? base
      : { ...base, failed: true, cause: toolResultCause(props.initial) };
  }
  const single = cardFrom(props.initial);
  if (single) {
    return {
      ...base,
      failed: false,
      card: single,
      cardResults: prev.cardResults + 1,
    };
  }
  const next = rootFromToolResult(props.initial);
  if (!next) return { ...base, failed: false };
  return withRoot({ ...base, failed: false }, next);
}

export function startState(props: RoomProps): RoomState {
  return resultChanged(NO_RESULT, props)
    ? applyResult(NO_RESULT, props)
    : NO_RESULT;
}
