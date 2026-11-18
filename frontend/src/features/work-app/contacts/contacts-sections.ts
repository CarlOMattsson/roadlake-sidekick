import type { WorkContactSummary } from "../transport/transport";

/** Letter headings show only when the list holds more Contacts than this; a shorter list is one flat list. */
export const LETTER_HEADINGS_ABOVE = 30;

/** Swedish order: Å, Ä and Ö come after Z. */
let swedishCollator: Intl.Collator | undefined;
function swedish(): Intl.Collator {
  swedishCollator ??= new Intl.Collator("sv");
  return swedishCollator;
}
const LETTER = /^\p{L}$/u;

/** The section letter of a name: its first letter in upper case, or "#" when it does not start with one. */
function sectionOf(name: string): string {
  const first = Array.from(name.trim())[0]?.toLocaleUpperCase("sv") ?? "";
  return LETTER.test(first) ? first : "#";
}

/** The Contacts by name, in Swedish order. */
export function sortedByName(
  items: WorkContactSummary[],
): WorkContactSummary[] {
  return [...items].sort((a, b) =>
    swedish().compare(a.display_name, b.display_name),
  );
}

/** Groups Contacts into sections by name, each section sorted by name in Swedish order. */
export function sectionsOf(
  items: WorkContactSummary[],
): { letter: string; contacts: WorkContactSummary[] }[] {
  const byLetter = new Map<string, WorkContactSummary[]>();
  for (const contact of sortedByName(items)) {
    const letter = sectionOf(contact.display_name);
    byLetter.set(letter, [...(byLetter.get(letter) ?? []), contact]);
  }
  return [...byLetter]
    .map(([letter, contacts]) => ({ letter, contacts }))
    .sort((a, b) => swedish().compare(a.letter, b.letter));
}

/**
 * A Contact's Tasks by how soon they are due: overdue first, then today and later, those without a date last. The
 * server lists them by last change, so a Task ticked off and back would otherwise move; equal dates keep that order.
 */
export function tasksByUrgency<T extends { due_at?: string | null }>(
  tasks: T[],
): T[] {
  const due = (task: T) => task.due_at ?? "￿";
  // ISO timestamps from the server sort as text.
  return [...tasks].sort((a, b) =>
    due(a) < due(b) ? -1 : due(a) > due(b) ? 1 : 0,
  );
}

/**
 * The profile line of a Contact: "relationship · role · organization" of the fields that are set, or ""
 * when none is. The list row's meta line and the line under the name in the Contact's own view both use
 * it, so the two say the same; each cuts the last part with an ellipsis. The address is never shown.
 */
export function contactMeta(
  contact: Pick<WorkContactSummary, "relationship" | "role" | "organization">,
): string {
  return [contact.relationship, contact.role, contact.organization]
    .map((part) => part?.trim())
    .filter(Boolean)
    .join(" · ");
}
