import { useMemo } from "react";
import { createJournalTransport } from "./transport";
import { roomEnabled } from "../mcp-apps/enabled-rooms";
import type { RoomTransport } from "../mcp-apps/room-types";
import { toolOffered } from "../mcp-apps/tool-support";

/**
 * What the host can answer, and the journal transport built from it. What the host cannot answer is not
 * offered (the mobile app has no originals, no drafts and no contact room).
 */
export function useRoomCapabilities(host: RoomTransport) {
  const call = host.call;
  const canReadSource = toolOffered(host, "get_journal_source");
  const canListPending = toolOffered(host, "list_pending_journal");
  // A contact name opens the Contact room only where that room is on; otherwise it stays plain text.
  const contactsOn = roomEnabled("contacts");
  const canOpenContact = contactsOn && toolOffered(host, "get_contact_context");
  // Changing a link needs rights a mobile Journal device does not hold, so the unlink is not offered there.
  const canChangeLinks = toolOffered(host, "update_journal_entry", {
    remove_contact_ids: [],
  });
  // Deleting an entry moves it to the trash and Undo restores it, so both tools must be there.
  const canTrash =
    toolOffered(host, "move_to_trash", { kind: "journal_entry" }) &&
    toolOffered(host, "restore_from_trash", { kind: "journal_entry" });
  // A linked Task shows by its title where it can be read and opened: get_task offered and the Work room on.
  const canReadTasks = roomEnabled("work") && toolOffered(host, "get_task");
  // Tags: the vocabulary needs list_tags; the filter also needs the tagged read; editing needs the tags write. The phone
  // answers none of them (its routes take no tags), so the room shows no filter and no tag editing there.
  const canListTags = toolOffered(host, "list_tags");
  const canFilterTags =
    canListTags && toolOffered(host, "list_journal_entries", { tags: [] });
  const canWriteTags = toolOffered(host, "update_journal_entry", { tags: [] });
  const transport = useMemo(
    () =>
      createJournalTransport(
        call,
        canReadSource,
        canChangeLinks,
        canTrash,
        canReadTasks,
        {
          vocabulary: canListTags,
          filter: canFilterTags,
          write: canWriteTags,
        },
      ),
    [
      call,
      canReadSource,
      canChangeLinks,
      canTrash,
      canReadTasks,
      canListTags,
      canFilterTags,
      canWriteTags,
    ],
  );
  return { transport, canListPending, contactsOn, canOpenContact };
}
