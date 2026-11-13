import type { EntryCardData } from "./entry-card";
import type { JournalEntryLink } from "./transport";

/**
 * A tool result that carries one entry record alone (create_manual_journal_entry) opens the
 * compact card. A result without a usable id and title is not a card and keeps the root rules.
 */
export function cardFrom(structured: unknown): EntryCardData | undefined {
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
