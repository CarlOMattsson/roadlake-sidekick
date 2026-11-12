/**
 * Which rooms a tool call may have changed. The shell re-reads a room another room wrote to
 * (docs/explanation/architecture/mcp-apps.md, "Entry, navigation and durable context"), so the adapters ask this after every tool
 * call a room makes. A read changes nothing. Writes are sorted by the tool name, not by arguments,
 * and err on the side of marking too many rooms: a needless re-read is cheap, a stale room is not.
 */
import type { RoomId } from "@/features/mcp-apps/router";

const READS = /^(get|list|search|show|recall)(_|$)/;

/** Tools that move or restore records of any domain. */
const EVERYWHERE = /^(move_to_trash|restore_from_trash|exclude_from_memory)$/;

/**
 * The domains a tool call with this name may have changed. Empty for a read. Control (Ändringar,
 * Papperskorg, Aktivitet, Minne) shows what every write changes, so every write marks it too.
 */
export function dirtyDomains(toolName: string): RoomId[] {
  if (READS.test(toolName)) return [];
  return [...domainsOfWrite(toolName), "control"];
}

/** The domains of a write other than Control, which every write marks (see dirtyDomains). */
function domainsOfWrite(toolName: string): RoomId[] {
  if (EVERYWHERE.test(toolName))
    return ["work", "journal", "contacts", "shopping"];
  if (toolName.includes("shopping")) return ["shopping"];
  // A draft that is finalized may create Tasks and link Contacts; an entry edit may link Contacts.
  if (toolName === "finalize_journal_draft")
    return ["journal", "work", "contacts"];
  if (toolName.includes("journal")) return ["journal", "contacts"];
  // Journal entries show Contact names, so a Contact write makes the Journal read again too.
  if (toolName.includes("contact")) return ["contacts", "work", "journal"];
  // Memory settings are shown only in Control, which every write marks.
  if (toolName === "set_memory_settings") return [];
  // A Project write makes the Journal read again too (as for Contacts).
  if (toolName.includes("project")) return ["work", "contacts", "journal"];
  // Tasks, Steps, saved views, processes, domains: Work, and the Contact pages list Tasks.
  return ["work", "contacts"];
}
