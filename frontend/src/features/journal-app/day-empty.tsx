import type { JournalLabels } from "./labels";
import { EmptyState } from "../mcp-apps/ui/states";

/**
 * An empty day has no section heading over nothing: one sentence, then the family's empty state with what to say
 * to Claude, and writing by hand as the secondary. One way to write at a time: while + has its choices open, or
 * the form is open, the empty day says only its sentence (and nothing once the form is open).
 */
export function DayEmpty({
  labels: t,
  isToday,
  composing,
  addOpen,
  canWrite,
  dayMessage,
  onTellClaude,
  onWriteYourself,
}: {
  labels: JournalLabels;
  isToday: boolean;
  composing: boolean;
  addOpen: boolean;
  canWrite: boolean;
  dayMessage: string;
  onTellClaude?: (text?: string) => void;
  onWriteYourself: () => void;
}) {
  const title = isToday ? t.noEntriesToday : t.noEntries;
  if (composing) return null;
  if (addOpen) return <p className="journal-empty">{title}</p>;
  return (
    <div className="journal-empty-state">
      <EmptyState
        title={title}
        ask={{
          locale: t.dateLocale,
          example: dayMessage,
          onSend: onTellClaude ? () => onTellClaude(dayMessage) : undefined,
        }}
      >
        {canWrite ? (
          <button
            type="button"
            className="sk-btn--secondary journal-write-self"
            onClick={onWriteYourself}
          >
            {t.writeYourself}
          </button>
        ) : null}
      </EmptyState>
    </div>
  );
}
