/**
 * The Journal room's tag calls: the owner's vocabulary (list_tags), the entries that carry given tags
 * (list_journal_entries with tags and tag_match "all") and the write of an entry's complete tag set
 * (update_journal_entry with tags). Each call is offered only where the host answers it; the transport leaves the rest out.
 */
import type { RoomTransport } from "../mcp-apps/room-types";
import type { ReadTags, TagRecord } from "../mcp-apps/ui/tag-vocabulary";
import { withEntry } from "./entry-result";
import type { JournalEntry } from "./transport";

/** One page of the tagged read: the entries without their content, and the cursor of the next page. */
export type JournalTaggedPage = {
  entries: JournalEntry[];
  next_cursor: string | null;
};

export type TagTransport = {
  /**
   * The owner's tag vocabulary (list_tags), for the suggestions and the filter. Optional: a host without list_tags
   * (the mobile app) leaves it out, and the room shows no filter and no suggestions.
   */
  listTags?: ReadTags;
  /**
   * One page of the entries that carry every one of `tags`, between the two days (YYYY-MM-DD, at most 366 days
   * apart), oldest first as the server lists them, without content. Optional: without it the day offers no tag filter.
   */
  listTaggedEntries?: (
    tags: string[],
    from: string,
    to: string,
    cursor: string | null,
  ) => Promise<JournalTaggedPage>;
  /**
   * Replaces the entry's tags (the complete set, [] clears them) at `version`. The answer is the entry with its new
   * version and tags. Optional: without it the entry shows its tags and offers no editing of them.
   */
  updateEntryTags?: (
    entryId: string,
    version: number,
    tags: string[],
    idempotencyKey: string,
  ) => Promise<{ entry: JournalEntry }>;
};

/** What the host answers of the tag calls. */
export type TagSupport = {
  vocabulary: boolean;
  filter: boolean;
  write: boolean;
};

export function createTagTransport(
  call: RoomTransport["call"],
  offered: TagSupport,
): TagTransport {
  return {
    ...(offered.vocabulary
      ? {
          // An answer without the list is a failed read, which leaves the room without suggestions and filter.
          listTags: () =>
            call<{ tags?: TagRecord[] }>("list_tags", { limit: 100 }).then(
              (page) => {
                if (!Array.isArray(page?.tags))
                  throw new Error("list_tags returned no tags");
                return page.tags;
              },
            ),
        }
      : {}),
    ...(offered.filter
      ? {
          listTaggedEntries: (
            tags: string[],
            from: string,
            to: string,
            cursor: string | null,
          ) =>
            call<JournalTaggedPage>("list_journal_entries", {
              from_date: from,
              to_date: to,
              tags,
              tag_match: "all",
              include_content: false,
              limit: 50,
              cursor,
            }),
        }
      : {}),
    ...(offered.write
      ? {
          updateEntryTags: (
            entryId: string,
            version: number,
            tags: string[],
            idempotencyKey: string,
          ) =>
            call<{ entry: JournalEntry }>("update_journal_entry", {
              entry_id: entryId,
              expected_version: version,
              idempotency_key: idempotencyKey,
              tags,
            }).then((result) => withEntry(result, "update_journal_entry")),
        }
      : {}),
  };
}
