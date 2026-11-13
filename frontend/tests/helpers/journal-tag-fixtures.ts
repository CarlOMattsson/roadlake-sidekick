import { vi } from "vitest";
import type { JournalEntry } from "@/features/journal-app/transport";
import type { TagRecord } from "@/features/mcp-apps/ui/tag-vocabulary";
import { entry } from "./journal-app-fixtures";

/** A vocabulary entry as list_tags returns it; `used` is its use on Journal entries. */
export function tagRecord(
  slug: string,
  label: string,
  used: number,
): TagRecord {
  return {
    id: `019f0000-0000-7000-8000-${slug.padEnd(12, "0").slice(0, 12)}`,
    slug,
    label,
    archived_at: null,
    created_at: "2026-10-01T09:00:00Z",
    updated_at: "2026-10-01T09:00:00Z",
    version: 1,
    usage: {
      contact: null,
      domain: null,
      journal_entry: used,
      process: null,
      project: null,
      task: null,
    },
  };
}

export const VIKTIG = tagRecord("viktig", "Viktig", 2);
export const FAMILJ = tagRecord("familj", "Familj", 1);
export const VOCABULARY = [VIKTIG, FAMILJ, tagRecord("vanta", "Vänta", 0)];

/** The tags read the room gets: the vocabulary above, as a mock. */
export function listTagsMock(tags: TagRecord[] = VOCABULARY) {
  return vi.fn(() => Promise.resolve(tags));
}

/** The owner's entry with these tags (slugs), under another id when `id` is given. */
export function taggedEntry(
  tags: string[],
  extra: Partial<JournalEntry> = {},
): JournalEntry {
  return { ...entry, tags, ...extra };
}
