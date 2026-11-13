import { useEffect, useEffectEvent, useMemo, useState } from "react";
import { WorkView } from "./view/work-view";
import { WorkFullscreen } from "./fullscreen/work-fullscreen";
import { RoomMessageContext } from "../mcp-apps/ui/room-context";
import { HierarchySummary } from "./inline/inline-summary";
import { workEn, workSv } from "./shared/labels";
import { cardLabelsFor } from "./shared/card-labels";
import { workShellLabelsFor } from "./shell/work-shell-labels";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "./inline/inline-summary-labels";
import { appLocale } from "../mcp-apps/app-locale";
import { toolResultCause } from "../mcp-apps/ui/states";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import type { RoomProps } from "../mcp-apps/room-types";
import { createWorkTransport } from "./transport/work-transport";
import { UnsortedView } from "./unsorted/unsorted-view";
import { rootFromToolResult, type WorkFrame } from "./transport/transport";
import type { WorkTab } from "./shell/work-shell";

/**
 * What the room holds. `seen*` say which result this state was derived from: a changed resultId,
 * initial or initialError is a new result, and the state is derived again from the previous one.
 */
type RoomState = {
  seenId?: number;
  seenInitial?: unknown;
  seenError?: boolean;
  /** Until the first tool result of this room; a room mounted hidden has none and reads for itself. */
  received: boolean;
  frame?: WorkFrame;
  /** The error result that opened an error frame, shaped as the bridge throws it: why the read failed. */
  cause?: Error;
  /** Set while Try again reads the first list again after an error result. */
  retrying: boolean;
  /** Counts the tool results that opened a frame; WorkFullscreen is keyed by it so its first tab is re-read. */
  resultNumber: number;
  /** Set while the host answers the fullscreen request; the inline Open shows it is busy, and a second press waits. */
  opening: boolean;
  /**
   * One card, one screen: inline, every root is a bounded summary. When the host offers no fullscreen,
   * Open expands the full view inline instead, so nothing is out of reach. A new result clears it.
   */
  expandedInline: boolean;
};

const NO_RESULT: RoomState = {
  received: false,
  retrying: false,
  resultNumber: 0,
  opening: false,
  expandedInline: false,
};

function resultChanged(state: RoomState, props: RoomProps): boolean {
  return (
    props.resultId !== state.seenId ||
    props.initial !== state.seenInitial ||
    props.initialError !== state.seenError
  );
}

/**
 * Every tool result that opens the room re-roots it; anything else is ignored. An error result
 * (isError) opens the error frame, not nothing.
 */
function applyResult(prev: RoomState, props: RoomProps): RoomState {
  const seen = {
    ...prev,
    seenId: props.resultId,
    seenInitial: props.initial,
    seenError: props.initialError,
    received: true,
  };
  const next = rootFromToolResult(props.initial, props.initialError === true);
  if (!next) return seen;
  return {
    ...seen,
    frame: next,
    cause: next.kind === "error" ? toolResultCause(props.initial) : undefined,
    retrying: false,
    expandedInline: false,
    resultNumber: prev.resultNumber + 1,
  };
}

function startState(props: RoomProps): RoomState {
  return resultChanged(NO_RESULT, props)
    ? applyResult(NO_RESULT, props)
    : NO_RESULT;
}

/** The tab a named start view stands for; other names are ignored. */
function startTabOf(view: string | undefined): WorkTab | undefined {
  return view === "agenda" || view === "board" || view === "hierarchy"
    ? view
    : undefined;
}

/** The tabs the host can serve; absent, or a list that names none of ours, is all of them. */
function tabsOf(views: readonly string[] | undefined): WorkTab[] | undefined {
  if (!views) return undefined;
  const tabs = (["agenda", "board", "hierarchy"] as const).filter((tab) =>
    views.includes(tab),
  );
  return tabs.length > 0 ? tabs : undefined;
}

/**
 * The work room: the Work app as one component. Fullscreen opens the tab shell for the three list and
 * board kinds; other kinds keep their view. Inline, every root is a bounded summary with Open. Mounted
 * without a result (hidden), fullscreen starts the tab shell, which reads its first tab itself.
 */
export function WorkRoom(props: RoomProps) {
  const [state, setState] = useState(() => startState(props));
  if (resultChanged(state, props)) {
    setState(applyResult(state, props));
  }
  const { call, supportsTool, supportsCall, offline } = props.transport;
  const transport = useMemo(
    () => createWorkTransport(call, { supportsTool, supportsCall }, offline),
    [call, supportsTool, supportsCall, offline],
  );
  const locale = appLocale();
  const labels = locale.startsWith("sv") ? workSv : workEn;
  const cardLabels = cardLabelsFor(locale);
  const inlineLabels = locale.startsWith("sv")
    ? inlineSummaryLabelsSv
    : inlineSummaryLabelsEn;
  const fullscreen = props.mode === "full";
  const { frame } = state;
  const { onNavigate } = props;
  // In the full view of a host that routes, Tasks and Projects open as steps on the shell's stack.
  const onRoute = fullscreen ? onNavigate : undefined;
  // A Journal entry under a Contact opens in the journal room. Without a host that routes, or with the room off, none is offered.
  const onOpenJournalEntry =
    onNavigate && roomEnabled("journal")
      ? (entry: { id: string; title: string }) =>
          onNavigate({ room: "journal", view: "entry", id: entry.id })
      : undefined;

  // An inline card that is mounted again after a write in the full view (refreshKey above 0) has no id to
  // read it by: the agenda and the board read themselves again with the filters the result carried.
  const inlineRefresh = !fullscreen && (props.refreshKey ?? 0) > 0;
  const openFrame = useEffectEvent(() => state.frame);
  useEffect(() => {
    const open = openFrame();
    if (!inlineRefresh || (open?.kind !== "agenda" && open?.kind !== "board"))
      return undefined;
    let live = true;
    const read: Promise<unknown> =
      open.kind === "agenda"
        ? transport.getWorkAgenda(open.filters)
        : transport.getWorkBoard(open.filters);
    read
      .then((page) => {
        if (!live) return;
        setState((prev) =>
          prev.frame === open
            ? ({ ...prev, frame: { ...open, page } } as RoomState)
            : prev,
        );
      })
      .catch(() => {
        // The card keeps what it shows; the next read corrects it.
      });
    return () => {
      live = false;
    };
  }, [inlineRefresh, transport]);

  function expandInline() {
    setState((prev) => ({ ...prev, expandedInline: true }));
    // The shell then draws the full view, with the room strip.
    props.onModeGranted?.("full");
  }
  /** Asks the host for fullscreen; the host may refuse, and the card then stays inline. */
  function requestFullscreen() {
    if (state.opening) return;
    setState((prev) => ({ ...prev, opening: true }));
    props.transport
      .requestDisplayMode("fullscreen")
      .catch(() => undefined)
      .finally(() => setState((prev) => ({ ...prev, opening: false })));
  }

  /**
   * Try again after an error result, which names no record: the list is what can be read again (the agenda, as the
   * fullscreen shell reads its first tab). A failure keeps the error card with what the new failure says.
   */
  function retryFirstList() {
    if (state.retrying) return;
    setState((prev) => ({ ...prev, retrying: true }));
    transport
      .getWorkAgenda({})
      .then((page) =>
        setState((prev) =>
          prev.frame?.kind === "error"
            ? {
                ...prev,
                frame: { kind: "agenda", filters: {}, page },
                cause: undefined,
                retrying: false,
                resultNumber: prev.resultNumber + 1,
              }
            : { ...prev, retrying: false },
        ),
      )
      .catch((cause: unknown) =>
        setState((prev) => ({
          ...prev,
          cause: cause instanceof Error ? cause : prev.cause,
          retrying: false,
        })),
      );
  }

  // The "To sort" page is a step on the shell's stack (no Back of its own); it holds no result.
  if (fullscreen && onRoute && props.view === "unsorted") {
    return (
      <section className="sidekick-work work-unsorted-page">
        <h2 className="work-unsorted-heading">{labels.unsortedHeading}</h2>
        <UnsortedView transport={transport} labels={labels} />
      </section>
    );
  }

  // Fullscreen opens the tab shell for the three list and board kinds; other kinds keep their view.
  const fullscreenTab =
    fullscreen &&
    (!state.received ||
      frame?.kind === "agenda" ||
      frame?.kind === "board" ||
      frame?.kind === "hierarchy" ||
      // An error result keeps the tab row: the start tab shows the read error under it.
      frame?.kind === "error");
  if (fullscreenTab) {
    return (
      <RoomMessageContext.Provider value={props.sendMessage}>
        <WorkFullscreen
          key={state.resultNumber}
          transport={transport}
          initial={frame}
          failure={frame?.kind === "error" ? { cause: state.cause } : undefined}
          startTab={startTabOf(props.view)}
          tabs={tabsOf(props.availableViews)}
          labels={labels}
          shellLabels={workShellLabelsFor(locale)}
          cardLabels={cardLabels}
          inlineLabels={inlineLabels}
          locale={locale}
          onOpenJournalEntry={onOpenJournalEntry}
          onRoute={onRoute}
          supportsTool={props.transport.supportsTool}
          hostSettings={props.hostSettings}
          refreshKey={props.refreshKey}
          active={props.active ?? true}
        />
      </RoomMessageContext.Provider>
    );
  }

  // "Open" on a work_changes card, a hierarchy summary or a root frame of WorkView: fullscreen when the
  // host offers it, else the full view expands inline (one card, one screen until the owner asks).
  const openAction =
    fullscreen || state.expandedInline
      ? undefined
      : props.fullscreenAvailable === true
        ? requestFullscreen
        : expandInline;
  if (frame?.kind === "hierarchy" && openAction) {
    // Inline: the hierarchy is only summarised here, Open asks for fullscreen or expands it. Expanded, the work view
    // below shows the Projects list, and a Project or Process opens on its stack.
    return (
      <RoomMessageContext.Provider value={props.sendMessage}>
        <section className="sidekick-work" aria-label={labels.title}>
          <HierarchySummary
            frame={frame}
            labels={inlineLabels}
            onOpen={openAction}
          />
        </section>
      </RoomMessageContext.Provider>
    );
  }
  return (
    <RoomMessageContext.Provider value={props.sendMessage}>
      <WorkView
        transport={transport}
        initial={frame}
        failure={
          frame?.kind === "error"
            ? {
                cause: state.cause,
                onRetry: retryFirstList,
                retrying: state.retrying,
              }
            : undefined
        }
        labels={labels}
        cardLabels={cardLabels}
        inlineLabels={inlineLabels}
        fullscreen={openAction}
        opening={state.opening}
        onModelContext={(summary) =>
          void props.transport.updateModelContext(summary)
        }
        shortcuts={fullscreen}
        onOpenJournalEntry={onOpenJournalEntry}
        onRoute={onRoute}
        supportsTool={props.transport.supportsTool}
        refreshKey={props.refreshKey}
        // Fullscreen has no card: the room strip says where the user is, and the page itself is the frame.
        chrome={!fullscreen}
      />
    </RoomMessageContext.Provider>
  );
}
