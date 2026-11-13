import { useEffect, useRef, useState } from "react";
import { JournalView } from "./journal-view";
import { EntryCard } from "./entry-card";
import { DayGlance } from "./day-glance";
import { journalEn, journalSv } from "./labels";
import { appLocale } from "../mcp-apps/app-locale";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { ownerToday } from "../mcp-apps/app-timezone";
import type { RoomProps } from "../mcp-apps/room-types";
import { applyResult, resultChanged, startState, withRoot } from "./room-state";
import type { JournalFrame, JournalPending } from "./transport";
import { useRoomActions } from "./use-room-actions";
import { useRoomCapabilities } from "./use-room-capabilities";

/**
 * The room props, plus the host's message function. `sendMessage` is present only when the host offers
 * messages (getFeatures().message); without it an empty day shows no "Tell Claude about the day" button.
 */
export type JournalRoomProps = RoomProps & {
  sendMessage?: (text: string) => Promise<boolean>;
};

/**
 * The journal room: all state and rendering of the Sidekick journal app. Inline, a day shows its glance
 * and a single entry its card; the day view itself is for fullscreen, or for the inline expansion when
 * the host offers no fullscreen. Mounted without a result, the view reads today for itself.
 */
export function JournalRoom(props: JournalRoomProps) {
  const [state, setState] = useState(() => startState(props));
  if (resultChanged(state, props)) {
    setState(applyResult(state, props));
  }
  const call = props.transport.call;
  const { transport, canListPending, contactsOn, canOpenContact } =
    useRoomCapabilities(props.transport);
  const locale = appLocale();
  const labels = locale.startsWith("sv") ? journalSv : journalEn;
  const fullscreen = props.mode === "full";
  const offersFullscreen = props.fullscreenAvailable === true && !fullscreen;
  const { card, frame, failed } = state;
  // The owner's today (the zone the shown day names, else the declared one), never the device's.
  const zone = frame?.kind === "day" ? frame.page.owner_timezone : undefined;

  // Inline, a day shows its glance (one card, one screen); the day view itself is for fullscreen, or
  // for the inline expansion when the host offers no fullscreen (Open sets dayInline then).
  const glance =
    !card && frame?.kind === "day" && !fullscreen && !state.dayInline
      ? frame.page
      : undefined;
  // Reads the pending items of the glance's day once per root, to count its drafts. Only the count is
  // kept: titles and text are not stored or logged. A failed read leaves the count out.
  const requestedFor = useRef<JournalFrame>(undefined);
  useEffect(() => {
    if (!canListPending) return;
    if (!glance || !frame || requestedFor.current === frame) return;
    requestedFor.current = frame;
    const journalDate = glance.journal_date;
    call<JournalPending>("list_pending_journal", {
      from_date: journalDate,
      to_date: journalDate,
    })
      .then((pending) => {
        const count = pending.items.filter(
          (item) => typeof item.draft_id === "string",
        ).length;
        setState((prev) =>
          prev.frame?.kind === "day" &&
          prev.frame.page.journal_date === journalDate
            ? { ...prev, drafts: { date: journalDate, count } }
            : prev,
        );
      })
      .catch(() => undefined);
  }, [glance, frame, call, canListPending]);

  // Mounted without any result (a room the strip opened), the room reads today for itself, once. Hidden behind an
  // entry (a root under a record that was opened directly), it waits until it is shown.
  const startedRead = useRef(false);
  const shown = props.active !== false;
  useEffect(() => {
    if (!shown || state.received || startedRead.current) return;
    startedRead.current = true;
    transport
      .getDay(ownerToday(zone))
      .then((page) =>
        setState((prev) =>
          prev.received || prev.frame
            ? prev
            : withRoot(prev, { kind: "day", page }),
        ),
      )
      .catch((cause: unknown) =>
        setState((prev) =>
          prev.received || prev.frame ? prev : { ...prev, failed: true, cause },
        ),
      );
  }, [shown, state.received, transport, zone]);

  const {
    retry,
    openCard,
    openDay,
    openGlanceEntry,
    openCardContact,
    openDrafts,
  } = useRoomActions({
    props,
    state,
    setState,
    transport,
    zone,
    offersFullscreen,
    canListPending,
  });

  if (failed) {
    const notice = (
      <ErrorNotice locale={locale} cause={state.cause} onRetry={retry} />
    );
    // Fullscreen: under the room's own chrome, as Work shows its read error. Inline: the card names the room.
    return fullscreen ? (
      <section
        className="sidekick-journal journal-fullscreen"
        aria-label={labels.title}
      >
        {notice}
      </section>
    ) : (
      <section className="sk-card">
        <p className="sk-eyebrow">{labels.title}</p>
        {notice}
      </section>
    );
  }
  if (card) {
    return (
      <EntryCard
        key={state.cardResults}
        entry={card}
        today={ownerToday(zone)}
        labels={labels}
        onOpen={openCard}
        onOpenContact={contactsOn ? openCardContact : undefined}
        opening={state.opening}
      />
    );
  }
  // The day's "tell Claude": the glance and the day view send the same message, only where the host takes messages.
  const tellClaude = props.sendMessage
    ? (text?: string) => {
        void props.sendMessage?.(text ?? labels.tellClaudeMessage);
      }
    : undefined;
  if (glance) {
    return (
      <DayGlance
        day={glance}
        today={ownerToday(zone)}
        draftCount={
          state.drafts?.date === glance.journal_date
            ? state.drafts.count
            : undefined
        }
        labels={labels}
        onOpen={openDay}
        onOpenEntry={openGlanceEntry}
        onReviewDrafts={openDrafts}
        onTellClaude={tellClaude}
        opening={state.dayOpening}
      />
    );
  }
  // Cross links exist only where the host can carry a tool call (onNavigate). Without it, no link is drawn.
  const navigate = props.onNavigate;
  return (
    <JournalView
      transport={transport}
      initial={frame}
      labels={labels}
      fullscreen={fullscreen}
      allEntries={state.dayInline}
      // With the shell's navigation, drill-ins go through it, so the shell's Back returns to the room.
      onRoute={props.onNavigate}
      refreshKey={props.refreshKey}
      hostSettings={fullscreen ? props.hostSettings : undefined}
      onTellClaude={tellClaude}
      onOpenContact={
        navigate && canOpenContact
          ? (link) =>
              navigate({
                room: "contacts",
                view: "contact",
                id: link.id,
                label: link.label ?? undefined,
              })
          : undefined
      }
      onOpenTask={
        navigate
          ? (id) => navigate({ room: "work", view: "task", id })
          : undefined
      }
    />
  );
}
