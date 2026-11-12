import { useContext, useState } from "react";
import { DraftFrame } from "./draft-review";
import type { JournalLabels } from "./labels";
import type { JournalFrame, JournalTransport } from "./transport";
import type { HostSettingsEntry, RoomTarget } from "../mcp-apps/room-types";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import { controlEntry } from "../mcp-apps/ui/control-entry";
import { appLocale } from "../mcp-apps/app-locale";
import { RoomSurfaceContext } from "../mcp-apps/ui/room-context";
import { DayFrame } from "./day-frame";
import { EntryFrame } from "./entry-frame";
import { SourceFrame } from "./source-frame";
import { PendingFrame } from "./pending-frame";
import "./journal.css";

/**
 * The room link of a frame that the view would open on its own stack. Day and pending frames have no
 * link: they stay inside the room.
 */
function routeOf(frame: JournalFrame): RoomTarget | undefined {
  switch (frame.kind) {
    case "entry":
      return { room: "journal", view: "entry", id: frame.id };
    case "draft":
      return { room: "journal", view: "draft", id: frame.id };
    case "source":
      return { room: "journal", view: "source", id: frame.id };
    default:
      return undefined;
  }
}

/** Both hosts use the same UI. The transport alone decides how data is read. */
export function JournalView({
  transport,
  initial,
  labels: t,
  fullscreen = false,
  allEntries = false,
  onOpenContact,
  onOpenTask,
  onRoute,
  refreshKey,
  onTellClaude,
  hostSettings,
}: {
  transport: JournalTransport;
  initial?: JournalFrame;
  labels: JournalLabels;
  /** Day shortcuts `[`, `]` and `t` work only in fullscreen. Inline views have none. */
  fullscreen?: boolean;
  /** A day opened inline from its glance shows every entry at once, not the first three. */
  allEntries?: boolean;
  /** Absent: contact chips are plain names. Present: a contact chip is a button that opens the contact. */
  onOpenContact?: (link: { id: string; label: string | null }) => void;
  /** Absent: the saved entry shows no task buttons. Present: each created task gets an "Open the task" button. */
  onOpenTask?: (id: string) => void;
  /**
   * Present (the shell's navigation): entries, drafts and originals open through it, not on the view's own
   * stack, so the shell's Back goes back. Absent: the view keeps its own stack and its own Back.
   */
  onRoute?: (target: RoomTarget) => void;
  /** Changes when the room should read again in place (a write elsewhere). The value at mount is not a request. */
  refreshKey?: number;
  /**
   * Present when the host can put a message in the conversation: an empty day then offers "Tell Claude about the
   * day", and a day with entries "+ Tell Claude more". Called with the message to send, or nothing for the default.
   */
  onTellClaude?: (text?: string) => void;
  /** The host's own settings (the phone): the day view's ⋯ ends with them instead of Control. */
  hostSettings?: HostSettingsEntry;
}) {
  // Drawn inside the Sidekick shell, the shell names the room: the app name stays for assistive technology only.
  const { framed } = useContext(RoomSurfaceContext);
  const [seen, setSeen] = useState(initial);
  const [stack, setStack] = useState<JournalFrame[]>(() =>
    initial ? [initial] : [],
  );
  // Bumped on every reset so a re-opened root always starts from fresh frames.
  const [session, setSession] = useState(0);
  // Bumped on every push or pop; a new frame moves focus to its heading only after a move.
  const [moves, setMoves] = useState(0);
  // Drafts the owner rejected or saved in this session; the pending list stops offering them.
  const [handled, setHandled] = useState<string[]>([]);
  // A new initial (a new tool result) replaces the whole navigation stack.
  if (initial !== seen) {
    setSeen(initial);
    setStack(initial ? [initial] : []);
    setSession((n) => n + 1);
    setMoves(0);
    setHandled([]);
  }
  const top = stack.at(-1);
  function open(frame: JournalFrame) {
    const target = routeOf(frame);
    if (onRoute && target) {
      onRoute(target);
      return;
    }
    setStack((current) => [...current, frame]);
    setMoves((n) => n + 1);
  }
  /** A day that moved to a neighbouring date replaces itself, wherever it sits in the stack. */
  function replaceFrame(before: JournalFrame, after: JournalFrame) {
    setStack((current) =>
      current.includes(before)
        ? current.map((frame) => (frame === before ? after : frame))
        : current,
    );
  }
  function draftHandled(draftId: string) {
    setHandled((current) =>
      current.includes(draftId) ? current : [...current, draftId],
    );
  }
  function back() {
    setStack((current) =>
      current.length > 1 ? current.slice(0, -1) : current,
    );
    setMoves((n) => n + 1);
  }
  return (
    <section
      className={
        fullscreen
          ? "sidekick-journal journal-fullscreen"
          : "sidekick-journal sk-card sk-card--root"
      }
      aria-label={t.title}
    >
      <header>
        <h1
          className={
            framed ? "sk-eyebrow journal-visually-hidden" : "sk-eyebrow"
          }
        >
          {t.title}
        </h1>
      </header>
      {stack.length > 1 && (
        <button
          type="button"
          className="journal-back sk-btn--quiet"
          onClick={back}
        >
          {t.back}
        </button>
      )}
      {!top && <p>{t.empty}</p>}
      {top?.kind === "day" && (
        <DayFrame
          key={`${session}:${stack.length}:day`}
          frame={top}
          onChange={(next) => replaceFrame(top, next)}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          fullscreen={fullscreen}
          allEntries={allEntries}
          refreshKey={refreshKey}
          onTellClaude={onTellClaude}
          control={
            hostSettings ??
            (fullscreen && onRoute && roomEnabled("control")
              ? {
                  label: controlEntry(appLocale()).label,
                  onOpen: () => onRoute(controlEntry(appLocale()).target),
                }
              : undefined)
          }
        />
      )}
      {top?.kind === "entry" && (
        <EntryFrame
          key={`${session}:${stack.length}:entry:${top.id}`}
          id={top.id}
          notice={top.notice}
          transport={transport}
          labels={t}
          moves={moves}
          onOpen={open}
          onOpenContact={onOpenContact}
          onOpenTask={onOpenTask}
          refreshKey={refreshKey}
        />
      )}
      {top?.kind === "draft" && (
        <DraftFrame
          key={`${session}:${stack.length}:draft:${top.id}`}
          id={top.id}
          transport={transport}
          labels={t}
          moves={moves}
          onRejected={draftHandled}
          onFinalized={(draftId, result) => {
            draftHandled(draftId);
            const notice = {
              created: result.created_task_ids.length,
              updated: result.updated_task_ids.length,
              createdTaskIds: result.created_task_ids,
            };
            // The shell replaces the draft's layer with the saved entry; Back never returns to a handled draft.
            if (onRoute) {
              onRoute({
                room: "journal",
                view: "entry",
                id: result.entry.id,
                replace: true,
                data: { entry: { id: result.entry.id }, notice },
              });
              return;
            }
            // The saved entry takes the place of the draft, so Back never returns to a handled draft.
            replaceFrame(top, {
              kind: "entry",
              id: result.entry.id,
              notice,
            });
            setMoves((n) => n + 1);
          }}
        />
      )}
      {top?.kind === "source" && (
        <SourceFrame
          key={`${session}:${stack.length}:source:${top.id}`}
          id={top.id}
          transport={transport}
          labels={t}
          moves={moves}
          onBack={onRoute ? undefined : back}
        />
      )}
      {top?.kind === "pending" && (
        <PendingFrame
          key={`${session}:${stack.length}:pending`}
          items={top.page.items.filter(
            (item) => !item.draft_id || !handled.includes(item.draft_id),
          )}
          labels={t}
          moves={moves}
          onOpen={open}
          fullscreen={fullscreen}
        />
      )}
    </section>
  );
}
