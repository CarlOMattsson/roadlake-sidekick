import { useEffect, useRef, useState } from "react";
import { formatCount, formatShortDateWithYear } from "./dates";
import { labelFor } from "./labels";
import type { JournalLabels } from "./labels";
import type { JournalFrame, JournalPendingItem } from "./transport";
import { ownerToday } from "../mcp-apps/app-timezone";
import { Row } from "../mcp-apps/ui/row";
import { EmptyState } from "../mcp-apps/ui/states";

/**
 * Inline, the pending list shows this many items; "Show all (N)" opens the rest in place. Three
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
  const today = ownerToday();
  const limited = !fullscreen && !expanded;
  const shownItems = limited ? items.slice(0, inlinePendingLimit) : items;
  return (
    <article>
      <h2 ref={heading} tabIndex={-1}>
        {t.pending}
      </h2>
      {/* The note asks to open a draft, so it stands only when there is one; an empty list is the family's empty state. */}
      {items.length === 0 ? (
        <EmptyState title={t.pendingEmpty} hint={t.pendingEmptyHint} />
      ) : (
        <p>{t.pendingNote}</p>
      )}
      {/* The row template: the draft's title opens it (›), one meta line (the date, the source kind and the `characters` count). A draft
          awaiting review names no state (the heading says it); any other state follows the date. */}
      <ul className="journal-pending-list">
        {shownItems.map((item) => {
          const draftId = item.draft_id;
          const state = labelFor(t.pendingState, item.state);
          // A source without a draft or a title is named by its state, which the meta then does not repeat.
          const title =
            item.draft_title ?? (draftId ? t.untitledDraft : undefined);
          const meta = [
            formatShortDateWithYear(item.journal_date, t.dateLocale, today),
            title === undefined || item.state === "draft_pending_review"
              ? undefined
              : state,
            labelFor(t.sourceType, item.source_type),
            `${formatCount(item.character_count, t.dateLocale)} ${t.characters}`,
          ].filter((part) => part !== undefined);
          return (
            <Row
              key={item.source_id}
              primary={title ?? state}
              secondary={meta.join(" · ")}
              navigates={Boolean(draftId)}
              onOpen={
                draftId
                  ? () => onOpen({ kind: "draft", id: draftId })
                  : undefined
              }
            />
          );
        })}
      </ul>
      {!fullscreen && items.length > inlinePendingLimit && (
        <p className="journal-list-more">
          <button
            type="button"
            className="sk-more"
            aria-expanded={expanded}
            onClick={() => setExpanded((open) => !open)}
            style={touchStyle}
          >
            {expanded ? t.showFewer : t.moreShowAll(items.length)}
          </button>
        </p>
      )}
    </article>
  );
}
