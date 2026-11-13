import { useMemo, useState } from "react";
import { WorkView } from "../view/work-view";
import { workEn, workSv } from "../shared/labels";
import { cardLabelsFor } from "../shared/card-labels";
import {
  inlineSummaryLabelsEn,
  inlineSummaryLabelsSv,
} from "../inline/inline-summary-labels";
import { appLocale } from "../../mcp-apps/app-locale";
import { roomEnabled } from "../../mcp-apps/enabled-rooms";
import type { RoomProps } from "../../mcp-apps/room-types";
import { RoomMessageContext } from "../../mcp-apps/ui/room-context";
import { ErrorNotice, toolResultCause } from "../../mcp-apps/ui/states";
import { createWorkTransport } from "../transport/work-transport";
import type { HostBridge } from "../../mcp-apps/bridge";
import { rootFromToolResult, type WorkFrame } from "../transport/transport";

/**
 * What the room holds. `seen*` say which result this state was derived from: a changed resultId,
 * initial or initialError is a new result, and the state is derived again from the previous one.
 */
type RoomState = {
  seenId?: number;
  seenInitial?: unknown;
  seenError?: boolean;
  /** The root of the room: the Contact list, one Contact, or the error frame. Never a Task or Project. */
  frame: WorkFrame;
  /** What the error frame's result said, for the notice's second line. */
  cause?: unknown;
  /** Set while the host answers the fullscreen request; Open shows it is busy, and a second press waits. */
  opening: boolean;
  /** Inline, with no fullscreen on offer, Open expands the full view in place. A new result clears it. */
  expandedInline: boolean;
};

/** The room's start when no result named a root: the unfiltered list, which the view reads for itself. */
const START_FRAME: WorkFrame = {
  kind: "contacts",
  q: "",
  includeArchived: false,
};

const NO_RESULT: RoomState = {
  frame: START_FRAME,
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

/** The frames that are Contacts business (list, one Contact, a Contact card) and the error frame. */
function isContactsRoot(frame: WorkFrame | undefined): frame is WorkFrame {
  return (
    frame?.kind === "contacts" ||
    frame?.kind === "contact" ||
    frame?.kind === "compact" ||
    frame?.kind === "error"
  );
}

/**
 * The names the Contacts room shows. The room is Contacts (Kontakter in Swedish) everywhere: the region the view
 * draws is named by `labels.title`, and the eyebrow of an inline or card summary by `appName`. Both
 * say the room's own name, not the Work app's "Arbete".
 */
export function contactsRoomNames(locale: string) {
  const base = locale.startsWith("sv") ? workSv : workEn;
  const inline = locale.startsWith("sv")
    ? inlineSummaryLabelsSv
    : inlineSummaryLabelsEn;
  const card = cardLabelsFor(locale);
  return {
    labels: { ...base, title: base.contacts },
    inlineLabels: { ...inline, appName: base.contacts },
    cardLabels: { ...card, appName: base.contacts },
  };
}

/** A result for another room (a Task, the board, ...) is not for this room and keeps what it shows. */
function applyResult(prev: RoomState, props: RoomProps): RoomState {
  const seen = {
    ...prev,
    seenId: props.resultId,
    seenInitial: props.initial,
    seenError: props.initialError,
  };
  const next = rootFromToolResult(props.initial, props.initialError === true);
  if (!isContactsRoot(next)) return seen;
  return {
    ...seen,
    frame: next,
    cause: next.kind === "error" ? toolResultCause(props.initial) : undefined,
    expandedInline: false,
  };
}

function startState(props: RoomProps): RoomState {
  return resultChanged(NO_RESULT, props)
    ? applyResult(NO_RESULT, props)
    : NO_RESULT;
}

/**
 * The Contacts room: the Contact list (A to Z with search and the archive switch), one Contact with its
 * linked Tasks and Projects, and Back, in a view of its own that needs no other Work tab. It reuses the
 * Work view stack (ContactsView, ContactFrame, ContactCard). Mounted without a result, it reads the list.
 */
export function ContactsRoom(props: RoomProps) {
  const [state, setState] = useState(() => startState(props));
  if (resultChanged(state, props)) {
    setState(applyResult(state, props));
  }
  const { call, supportsTool, supportsCall } = props.transport;
  const transport = useMemo(
    () => createWorkTransport(call, { supportsTool, supportsCall }),
    [call, supportsTool, supportsCall],
  );
  const locale = appLocale();
  const names = contactsRoomNames(locale);
  const fullscreen = props.mode === "full";
  const { onNavigate } = props;
  // The room transport is the bridge itself; ui/open-link is offered only where it exists.
  const openLink = (props.transport as Partial<HostBridge>).openLink;
  // A Journal entry under the Contact opens in the journal room. Without a host that routes, or with the room off, none is offered.
  const onOpenJournalEntry =
    onNavigate && roomEnabled("journal")
      ? (entry: { id: string; title: string }) =>
          onNavigate({ room: "journal", view: "entry", id: entry.id })
      : undefined;

  /** Asks the host for fullscreen; the host may refuse, and the card then stays inline. */
  function requestFullscreen() {
    if (state.opening) return;
    setState((prev) => ({ ...prev, opening: true }));
    props.transport
      .requestDisplayMode("fullscreen")
      .catch(() => undefined)
      .finally(() => setState((prev) => ({ ...prev, opening: false })));
  }
  function expandInline() {
    setState((prev) => ({ ...prev, expandedInline: true }));
    // The shell then draws the full view, with the room strip.
    props.onModeGranted?.("full");
  }

  // Inline with fullscreen on offer the root is a summary and Open asks for fullscreen; with none on
  // offer Open expands the full view in place. In the full view there is no Open.
  const openAction =
    fullscreen || state.expandedInline
      ? undefined
      : props.fullscreenAvailable === true
        ? requestFullscreen
        : expandInline;
  // A failed first result: the error result names no tool and no record, so Try again reads the list afresh and the
  // heading names that read ("Kontakterna"), whichever Contact tool failed.
  const retryList = () => setState((prev) => ({ ...prev, frame: START_FRAME }));
  if (fullscreen && state.frame.kind === "error")
    return (
      // In the room's own frame (padding, type), where its list would stand.
      <section className="sidekick-work" aria-label={names.labels.title}>
        <ErrorNotice
          locale={locale}
          subject="contacts"
          cause={state.cause}
          onRetry={retryList}
        />
      </section>
    );
  return (
    <RoomMessageContext.Provider value={props.sendMessage}>
      <WorkView
        transport={transport}
        initial={state.frame}
        failure={
          state.frame.kind === "error"
            ? {
                cause: state.cause,
                subject: "contacts",
                onRetry: retryList,
                retrying: false,
              }
            : undefined
        }
        labels={names.labels}
        cardLabels={names.cardLabels}
        inlineLabels={names.inlineLabels}
        fullscreen={openAction}
        opening={state.opening}
        shortcuts={fullscreen}
        onOpenJournalEntry={onOpenJournalEntry}
        // Kontaktvägar opens e-mail and phone through the host (ui/open-link).
        onOpenLink={openLink && ((url) => void openLink(url))}
        // In the full view of a host that routes, a Contact, Task or Project is a step on the shell's stack.
        onRoute={fullscreen ? onNavigate : undefined}
        refreshKey={props.refreshKey}
        // The room strip says where the user is, so the app name stays only as a hidden heading.
        chrome={!fullscreen}
      />
    </RoomMessageContext.Provider>
  );
}
