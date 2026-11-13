import { useId, useState, type RefObject } from "react";
import type { JournalLabels } from "./labels";
import type { JournalFrame, JournalTransport } from "./transport";
import { KeyScope } from "../mcp-apps/ui/key-scope";
import { PlusIcon } from "../mcp-apps/ui/icons";
import { ownerNoon } from "../mcp-apps/app-timezone";

/** A new entry on another day than today sits on that day (noon, owner zone); on today the server decides. */
function occurredAtFor(
  date: string,
  today: string,
  zone?: string,
): string | undefined {
  if (date === today) return undefined;
  return ownerNoon(date, zone);
}

type DayFrameValue = Extract<JournalFrame, { kind: "day" }>;

type DayWriteInput = {
  frame: DayFrameValue;
  transport: JournalTransport;
  onChange: (next: JournalFrame) => void;
  mounted: { current: boolean };
  today: string;
  /** The day is not shown (its read failed) or is a tagged list: there is nothing to write on. */
  failedDate?: string;
  filtered: boolean;
  /** Asks Claude about the day; absent where the host offers no messages. */
  onTellClaude?: (text?: string) => void;
  /** Asks Claude for more on a day that has notes; absent otherwise. */
  tellMore?: () => void;
  dayMessage: string;
};

/**
 * Writing by hand (see docs/decisions/log.md D-076: the journal is written by hand, no AI): the + menu, the open
 * form, and the line after a saved entry. With a transport that can write, + also holds writing by hand: together
 * with Claude it opens a two-item menu, alone it opens the form. Without a writing transport it is the old
 * "Tell Claude more".
 */
export function useDayWrite({
  frame,
  transport,
  onChange,
  mounted,
  today,
  failedDate,
  filtered,
  onTellClaude,
  tellMore,
  dayMessage,
}: DayWriteInput) {
  const [addOpen, setAddOpen] = useState(false);
  const [composing, setComposing] = useState(false);
  const [created, setCreated] = useState(false);
  const panelId = useId();
  const { page } = frame;

  const canWrite = transport.writeEntry !== undefined && !failedDate;
  const tellClaudeAction = onTellClaude
    ? () => (tellMore ? tellMore() : onTellClaude(dayMessage))
    : undefined;
  function startComposing() {
    setCreated(false);
    setComposing(true);
  }
  // With a tag chosen the view is a list over many days and no day is shown, so + has no day to write on: it is gone
  // until the filter is cleared or a day is tapped in the strip (either shows that day, + included).
  const addAction = filtered
    ? undefined
    : canWrite
      ? () => {
          if (tellClaudeAction) setAddOpen((open) => !open);
          else startComposing();
        }
      : tellMore;

  function writeEntry(
    values: { title: string; text: string },
    idempotencyKey: string,
  ): Promise<void> {
    const write = transport.writeEntry;
    if (!write) return Promise.reject(new Error("no writeEntry"));
    const journalDate = page.journal_date;
    const occurredAt = occurredAtFor(journalDate, today, page.owner_timezone);
    return write(
      {
        journal_date: journalDate,
        title: values.title,
        source_text: values.text,
        ...(occurredAt ? { occurred_at: occurredAt } : {}),
      },
      idempotencyKey,
    ).then(({ entry }) => {
      setComposing(false);
      setCreated(true);
      // The day is read again so the entry sits where the server puts it; if that read fails the entry is added here.
      return transport.getDay(journalDate).then(
        (next) => {
          if (mounted.current) onChange({ ...frame, page: next });
        },
        () => {
          if (mounted.current)
            onChange({
              ...frame,
              page: { ...page, entries: [...page.entries, entry] },
            });
        },
      );
    });
  }

  return {
    addOpen,
    setAddOpen,
    composing,
    setComposing,
    created,
    clearCreated: () => setCreated(false),
    panelId,
    canWrite,
    tellClaudeAction,
    addAction,
    startComposing,
    writeEntry,
    filtered,
  };
}

export type DayWrite = ReturnType<typeof useDayWrite>;

/** The day's one primary: the round ink + of the list views, 4 before ⋯. */
export function DayAddButton({
  write,
  buttonRef,
  labels: t,
  loading,
}: {
  write: DayWrite;
  buttonRef: RefObject<HTMLButtonElement | null>;
  labels: JournalLabels;
  loading: boolean;
}) {
  const { canWrite, tellClaudeAction, addOpen, addAction } = write;
  return (
    <button
      ref={buttonRef}
      type="button"
      className="sk-iconbtn sk-iconbtn--primary journal-day-add"
      aria-label={canWrite ? t.addEntry : t.tellClaude}
      title={canWrite ? t.addEntry : t.tellClaude}
      aria-expanded={canWrite && tellClaudeAction ? addOpen : undefined}
      aria-controls={
        canWrite && tellClaudeAction && addOpen ? write.panelId : undefined
      }
      aria-disabled={loading || undefined}
      onClick={() => {
        if (!loading) addAction?.();
      }}
    >
      <PlusIcon />
    </button>
  );
}

/**
 * Mounted only while open: a closed panel between the week and the content would part the strip from the
 * summary and heading that follow it (journal.css).
 */
export function DayAddPanel({
  write,
  buttonRef,
  labels: t,
}: {
  write: DayWrite;
  buttonRef: RefObject<HTMLButtonElement | null>;
  labels: JournalLabels;
}) {
  const { canWrite, tellClaudeAction, addOpen, filtered } = write;
  if (!(canWrite && tellClaudeAction && addOpen && !filtered)) return null;
  return (
    <KeyScope
      id={write.panelId}
      className="journal-add-panel"
      onEscape={() => {
        write.setAddOpen(false);
        buttonRef.current?.focus();
      }}
    >
      {/* Two real buttons, one way each: Claude asks, or the user writes. */}
      <button
        type="button"
        className="sk-btn--primary journal-add-choice"
        onClick={() => {
          write.setAddOpen(false);
          tellClaudeAction();
        }}
      >
        {t.tellClaude}
      </button>
      <button
        type="button"
        className="sk-btn--secondary journal-add-choice"
        onClick={() => {
          write.setAddOpen(false);
          write.startComposing();
        }}
      >
        {t.writeYourself}
      </button>
      <p className="journal-add-hint">{t.tellClaudeHint}</p>
    </KeyScope>
  );
}
