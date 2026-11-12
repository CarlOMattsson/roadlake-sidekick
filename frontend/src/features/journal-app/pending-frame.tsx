import { useEffect, useRef, useState } from "react";
import { formatCalendarDate, formatCount } from "./dates";
import { labelFor } from "./labels";
import type { JournalLabels } from "./labels";
import type { JournalFrame, JournalPendingItem } from "./transport";

/**
 * Inline, the pending list shows this many items; "+N more · Show all" opens the rest in place. Three
 * is what fits a 560 px card at 320 px wide (measured): each row has a two-line title and a meta line.
 */
const inlinePendingLimit = 3;
const touchStyle = { minHeight: "44px" };

export function PendingFrame({
  items,
  labels: t,
  moves,
  onOpen,
  fullscreen,
}: {
  items: JournalPendingItem[];
  labels: JournalLabels;
  moves: number;
  onOpen: (frame: JournalFrame) => void;
  fullscreen: boolean;
}) {
  const heading = useRef<HTMLHeadingElement>(null);
  // The rest of the list, shown inline in place. A new root starts collapsed again.
  const [expanded, setExpanded] = useState(false);
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  const limited = !fullscreen && !expanded;
  const shownItems = limited ? items.slice(0, inlinePendingLimit) : items;
  return (
    <article>
      <h2 ref={heading} tabIndex={-1}>
        {t.pending}
      </h2>
      <p>{t.pendingNote}</p>
      {items.length === 0 && <p>{t.pendingEmpty}</p>}
      <ul className="journal-list journal-pending-list">
        {shownItems.map((item) => (
          <li key={item.source_id}>
            <p>
              {formatCalendarDate(item.journal_date, t.dateLocale)} ·{" "}
              {labelFor(t.sourceType, item.source_type)}
            </p>
            {item.draft_id ? (
              <button
                type="button"
                onClick={() =>
                  onOpen({ kind: "draft", id: item.draft_id as string })
                }
              >
                {item.draft_title ?? t.untitledDraft}
              </button>
            ) : (
              item.draft_title && <p>{item.draft_title}</p>
            )}
            <p className="journal-muted">
              {labelFor(t.pendingState, item.state)} ·{" "}
              {formatCount(item.character_count, t.dateLocale)} {t.characters}
            </p>
          </li>
        ))}
      </ul>
      {!fullscreen && items.length > inlinePendingLimit && (
        <p>
          <button
            type="button"
            className="sk-btn--quiet"
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
            style={touchStyle}
          >
            {expanded
              ? t.pendingLess
              : t.pendingMore(items.length - inlinePendingLimit)}
          </button>
        </p>
      )}
    </article>
  );
}
