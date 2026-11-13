import type { Dispatch, SetStateAction } from "react";
import { withEntry, withRoot, type RoomState } from "./room-state";
import type {
  JournalEntryLink,
  JournalPending,
  JournalTransport,
} from "./transport";
import { ownerToday } from "../mcp-apps/app-timezone";
import type { RoomProps } from "../mcp-apps/room-types";

type RoomActionsInput = {
  props: RoomProps;
  state: RoomState;
  setState: Dispatch<SetStateAction<RoomState>>;
  transport: JournalTransport;
  zone: string | undefined;
  offersFullscreen: boolean;
  canListPending: boolean;
};

/**
 * What the owner can do from the card, the day glance and the error notice: Retry, Open, and the links out
 * of them. They all ask the host for fullscreen first when it offers it, and fall back to inline.
 */
export function useRoomActions({
  props,
  state,
  setState,
  transport,
  zone,
  offersFullscreen,
  canListPending,
}: RoomActionsInput) {
  const { card, frame } = state;

  /** Changes the state with a part or with a function of the newest state (answers arrive later). */
  function patch(change: Partial<RoomState>) {
    setState((prev) => ({ ...prev, ...change }));
  }

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
    props.transport
      .call<JournalPending>("list_pending_journal", {
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

  return {
    retry,
    openCard,
    openDay,
    openGlanceEntry,
    openCardContact,
    openDrafts,
  };
}
