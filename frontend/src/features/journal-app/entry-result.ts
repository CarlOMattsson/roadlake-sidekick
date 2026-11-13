import type { JournalEntry } from "./transport";

/** The write's answer when it carries an entry with an id and a version; anything else is a failed write. */
export function withEntry(
  result: { entry: JournalEntry },
  tool: string,
): { entry: JournalEntry } {
  const entry = (result as { entry?: Partial<JournalEntry> } | null)?.entry;
  if (
    typeof entry !== "object" ||
    entry === null ||
    typeof entry.id !== "string" ||
    typeof entry.version !== "number"
  )
    throw new Error(`${tool} returned no entry`);
  return result;
}
