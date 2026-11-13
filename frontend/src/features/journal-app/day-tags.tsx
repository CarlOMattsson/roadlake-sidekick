import { useEffect, useRef } from "react";
import type { JournalLabels } from "./labels";
import { TaggedEntries } from "./tagged-entries";
import type { JournalFrame, JournalTransport } from "./transport";
import { ownerToday } from "../mcp-apps/app-timezone";
import { TagFilter } from "../mcp-apps/ui/tags";
import { useTagVocabulary } from "../mcp-apps/ui/tag-vocabulary";

/**
 * The tag side of the day view: the tags the day is filtered on, whether that filter is on (the host can read tagged
 * entries), and the owner's vocabulary. A changed `refreshKey` (a write elsewhere) reads the vocabulary again.
 */
export function useDayTags(
  transport: JournalTransport,
  chosen: string[] | undefined,
  refreshKey: number | undefined,
) {
  const vocabulary = useTagVocabulary(transport.listTags, "journal_entry");
  const refresh = vocabulary.refresh;
  const atMount = useRef(refreshKey);
  useEffect(() => {
    if (refreshKey === atMount.current) return;
    atMount.current = refreshKey;
    refresh();
  }, [refreshKey, refresh]);
  const tags = chosen ?? [];
  return {
    tags,
    filtered: tags.length > 0 && transport.listTaggedEntries !== undefined,
    vocabulary,
  };
}

/**
 * The filter row under the day's strip, shown only where tags are in use on entries, and, once a tag is chosen, the
 * list of the tagged entries that takes the place of the day's content. Choosing nothing returns to the day.
 */
export function DayTags({
  state: { tags, vocabulary },
  frame,
  transport,
  labels,
  refreshKey,
  onChange,
  onOpen,
}: {
  state: ReturnType<typeof useDayTags>;
  frame: Extract<JournalFrame, { kind: "day" }>;
  transport: JournalTransport;
  labels: JournalLabels;
  refreshKey?: number;
  onChange: (next: JournalFrame) => void;
  onOpen: (frame: JournalFrame) => void;
}) {
  if (!transport.listTaggedEntries) return null;
  return (
    <>
      <TagFilter
        options={vocabulary.options}
        selected={tags}
        onChange={(next) => onChange({ ...frame, tags: next })}
        locale={labels.dateLocale}
      />
      {tags.length > 0 && (
        <TaggedEntries
          key={tags.join(",")}
          tags={tags}
          today={ownerToday(frame.page.owner_timezone)}
          transport={transport}
          labels={labels}
          vocabulary={vocabulary.suggestions}
          refreshKey={refreshKey}
          onOpen={(id) => onOpen({ kind: "entry", id })}
        />
      )}
    </>
  );
}
