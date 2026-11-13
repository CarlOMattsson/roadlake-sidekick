import { useEffect, useMemo, useRef, useState } from "react";
import { JournalView } from "./journal-view";
import { EntryCard, type EntryCardData } from "./entry-card";
import { DayGlance } from "./day-glance";
import { journalEn, journalSv } from "./labels";
import { appLocale } from "../mcp-apps/app-locale";
import { ErrorNotice, toolResultCause } from "../mcp-apps/ui/states";
import { ownerToday } from "../mcp-apps/app-timezone";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { toolOffered } from "../mcp-apps/tool-support";
import type { RoomProps } from "../mcp-apps/room-types";
import {
  createJournalTransport,
  rootFromToolResult,
  type JournalEntryLink,
  type JournalFrame,
  type JournalPending,
} from "./transport";

/**
 * What the room holds. The fields up to `received` say which result this state was derived from: a
 * changed resultId, initial or initialError is a new result, and the state is derived again from the
 * previous one (during render, as JournalView does with its `initial`).
 */
type RoomState = {
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

function resultChanged(state: RoomState, props: RoomProps): boolean {
  return (
    props.resultId !== state.seenId ||
    props.initial !== state.seenInitial ||
    props.initialError !== state.seenError
  );
}

/** A new root replaces the view; the card, its notices, the inline day and the draft count start again. */
function withRoot(prev: RoomState, frame: JournalFrame): RoomState {
  return {
    ...prev,
    frame,
    card: undefined,
    dayInline: false,
    drafts: undefined,
  };
}

/** Shows the existing entry view for one entry, replacing the card. */
function withEntry(prev: RoomState, id: string): RoomState {
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
function applyResult(prev: RoomState, props: RoomProps): RoomState {
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

function startState(props: RoomProps): RoomState {
  return resultChanged(NO_RESULT, props)
    ? applyResult(NO_RESULT, props)
    : NO_RESULT;
}

/**
 * A tool result that carries one entry record alone (create_manual_journal_entry) opens the
 * compact card. A result without a usable id and title is not a card and keeps the root rules.
 */
function cardFrom(structured: unknown): EntryCardData | undefined {
  const entry = (structured as { entry?: unknown } | null | undefined)?.entry;
  if (typeof entry !== "object" || entry === null) return undefined;
  const {
    id,
    title,
    summary,
    source_id,
    journal_date,
    occurred_at,
    contact_ids,
    task_ids,
    tags,
    version,
    links,
  } = entry as Record<string, unknown>;
  if (typeof id !== "string" || typeof title !== "string") return undefined;
  if (version !== undefined && typeof version !== "number") return undefined;
  if (summary !== undefined && summary !== null && typeof summary !== "string")
    return undefined;
  if (journal_date !== undefined && typeof journal_date !== "string")
    return undefined;
  if (
    occurred_at !== undefined &&
    occurred_at !== null &&
    typeof occurred_at !== "string"
  )
    return undefined;
  if (
    !isStringList(contact_ids) ||
    !isStringList(task_ids) ||
    !isStringList(tags)
  )
    return undefined;
  if (!isLinkList(links)) return undefined;
  return {
    id,
    title,
    summary: typeof summary === "string" ? summary : null,
    source_id: typeof source_id === "string" ? source_id : undefined,
    journal_date: typeof journal_date === "string" ? journal_date : undefined,
    occurred_at: typeof occurred_at === "string" ? occurred_at : null,
    contact_ids,
    task_ids,
    tags,
    version: typeof version === "number" ? version : undefined,
    links: links?.map((link) => ({
      kind: link.kind,
      id: link.id,
      label: link.label ?? null,
    })),
  };
}
function isStringList(value: unknown): value is string[] | undefined {
  return (
    value === undefined ||
    (Array.isArray(value) && value.every((id) => typeof id === "string"))
  );
}
/** The links of a result: absent, or a list of Projects and Contacts with an id and a name or null. */
function isLinkList(value: unknown): value is JournalEntryLink[] | undefined {
  return value === undefined || (Array.isArray(value) && value.every(isLink));
}
function isLink(value: unknown): value is JournalEntryLink {
  if (typeof value !== "object" || value === null) return false;
  const { kind, id, label } = value as Record<string, unknown>;
  return (
    (kind === "project" || kind === "contact") &&
    typeof id === "string" &&
    (label === undefined || label === null || typeof label === "string")
  );
}

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
  // What the host cannot answer is not offered (the mobile app has no originals, no drafts and no contact room).
  const canReadSource = toolOffered(props.transport, "get_journal_source");
  const canListPending = toolOffered(props.transport, "list_pending_journal");
  // A contact name opens the Contact room only where that room is on; otherwise it stays plain text.
  const contactsOn = roomEnabled("contacts");
  const canOpenContact =
    contactsOn && toolOffered(props.transport, "get_contact_context");
  // Changing a link needs rights a mobile Journal device does not hold, so the unlink is not offered there.
  const canChangeLinks = toolOffered(props.transport, "update_journal_entry", {
    remove_contact_ids: [],
  });
  // Deleting an entry moves it to the trash and Undo restores it, so both tools must be there.
  const canTrash =
    toolOffered(props.transport, "move_to_trash", { kind: "journal_entry" }) &&
    toolOffered(props.transport, "restore_from_trash", {
      kind: "journal_entry",
    });
  // A linked Task shows by its title where it can be read and opened: get_task offered and the Work room on.
  const canReadTasks =
    roomEnabled("work") && toolOffered(props.transport, "get_task");
  // Tags: the vocabulary needs list_tags; the filter also needs the tagged read; editing needs the tags write. The phone
  // answers none of them (its routes take no tags), so the room shows no filter and no tag editing there.
  const canListTags = toolOffered(props.transport, "list_tags");
  const canFilterTags =
    canListTags &&
    toolOffered(props.transport, "list_journal_entries", { tags: [] });
  const canWriteTags = toolOffered(props.transport, "update_journal_entry", {
    tags: [],
  });
  const transport = useMemo(
    () =>
      createJournalTransport(
        call,
        canReadSource,
        canChangeLinks,
        canTrash,
        canReadTasks,
        {
          vocabulary: canListTags,
          filter: canFilterTags,
          write: canWriteTags,
        },
      ),
    [
      call,
      canReadSource,
      canChangeLinks,
      canTrash,
      canReadTasks,
      canListTags,
      canFilterTags,
      canWriteTags,
    ],
  );
  const locale = appLocale();
  const labels = locale.startsWith("sv") ? journalSv : journalEn;
  const fullscreen = props.mode === "full";
  const offersFullscreen = props.fullscreenAvailable === true && !fullscreen;
  const { card, frame, failed } = state;
  // The owner's today (the zone the shown day names, else the declared one), never the device's.
  const zone = frame?.kind === "day" ? frame.page.owner_timezone : undefined;

  /** Changes the state with a part or with a function of the newest state (answers arrive later). */
  function patch(change: Partial<RoomState>) {
    setState((prev) => ({ ...prev, ...change }));
  }

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

  /**
   * Retry reads today's journal day again, through the same transport read the day view uses; a day
   * without entries shows as empty. A failed read keeps the generic notice; the error text itself is
   * never shown or logged.
   */
  function retry() {
    if (state.retrying) return;
    patch({ retrying: true });
    transport
      .getDay(ownerToday(zone))
      .then((page) =>
        setState((prev) => ({
          ...withRoot(prev, { kind: "day", page }),
          retrying: false,
          failed: false,
        })),
      )
      .catch((cause: unknown) => patch({ retrying: false, cause }));
  }

  /**
   * Open asks the host for fullscreen, the same way the work and shopping apps do, and shows the
   * entry view once the host answers. When the host does not offer fullscreen, or refuses or fails
   * the request, the entry view opens inline in the card's place (the fallback). Nothing about the
   * entry is sent to the host or logged on this path, per docs/decisions/log.md D-058 (logs and telemetry never carry user content).
   */
  function openCard() {
    const entry = card;
    if (!entry || state.opening) return;
    if (!offersFullscreen) {
      setState((prev) => withEntry(prev, entry.id));
      props.onModeGranted?.("full");
      return;
    }
    patch({ opening: true });
    props.transport
      .requestDisplayMode("fullscreen")
      .catch(() => undefined)
      .finally(() =>
        // A newer tool result may have replaced the card while the host answered; then it stays.
        setState((prev) =>
          prev.card === entry
            ? { ...withEntry(prev, entry.id), opening: false }
            : { ...prev, opening: false },
        ),
      );
  }

  /**
   * Open on the day glance asks the host for fullscreen, the same way the entry card does, and the
   * day view shows there. When the host refuses or fails the request, the day view opens inline in
   * the glance's place (the fallback). Nothing about the day is sent to the host or logged here.
   */
  function openDay() {
    if (state.dayOpening) return;
    if (!offersFullscreen) {
      // No fullscreen on offer: the day expands inline in the glance's place.
      patch({ dayInline: true });
      props.onModeGranted?.("full");
      return;
    }
    patch({ dayOpening: true });
    props.transport
      .requestDisplayMode("fullscreen")
      .then((mode) => {
        if (mode === "fullscreen") props.onModeGranted?.("full");
        else {
          patch({ dayInline: true });
          props.onModeGranted?.("full");
        }
      })
      .catch(() => {
        patch({ dayInline: true });
        props.onModeGranted?.("full");
      })
      .finally(() => patch({ dayOpening: false }));
  }

  /**
   * A row of the day glance opens its entry the way Open does: fullscreen first when the host offers it,
   * then the entry view; inline otherwise. Nothing about the entry is sent to the host or logged here.
   */
  function openGlanceEntry(id: string) {
    if (state.dayOpening) return;
    if (!offersFullscreen) {
      setState((prev) => withEntry(prev, id));
      props.onModeGranted?.("full", { room: "journal", view: "entry", id });
      return;
    }
    patch({ dayOpening: true });
    props.transport
      .requestDisplayMode("fullscreen")
      .catch(() => undefined)
      .finally(() => {
        setState((prev) => ({ ...withEntry(prev, id), dayOpening: false }));
        props.onModeGranted?.("full", { room: "journal", view: "entry", id });
      });
  }

  /**
   * A contact name on the entry card opens that Contact in the full view (design 5.1): fullscreen
   * first when the host offers it, then the shell shows the Contact on top of this card's entry. The
   * name is the only thing sent as the target's label; no journal text leaves the card.
   */
  function openCardContact(link: JournalEntryLink) {
    const target = {
      room: "contacts" as const,
      view: "contact",
      id: link.id,
      label: link.label ?? undefined,
    };
    if (!offersFullscreen) {
      props.onModeGranted?.("full", target);
      return;
    }
    props.transport
      .requestDisplayMode("fullscreen")
      .catch(() => undefined)
      .finally(() => props.onModeGranted?.("full", target));
  }

  /**
   * "Review N drafts" reads the day's pending items once more and shows them in the app, as the pending
   * view. The read is the same as the glance's count read; the rows are kept only in the view. A failed
   * read leaves the glance as it is.
   */
  function openDrafts() {
    if (frame?.kind !== "day" || !canListPending) return;
    const journalDate = frame.page.journal_date;
    call<JournalPending>("list_pending_journal", {
      from_date: journalDate,
      to_date: journalDate,
    })
      .then((pending) =>
        setState((prev) =>
          prev.frame?.kind === "day" &&
          prev.frame.page.journal_date === journalDate
            ? withRoot(prev, { kind: "pending", page: pending })
            : prev,
        ),
      )
      .catch(() => undefined);
  }

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
      onTellClaude={
        props.sendMessage
          ? (text?: string) => {
              void props.sendMessage?.(text ?? labels.tellClaudeMessage);
            }
          : undefined
      }
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
