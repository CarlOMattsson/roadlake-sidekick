import { roomEnabled } from "../../mcp-apps/enabled-rooms";
import { useToolSupport } from "../../mcp-apps/tool-support";
import {
  TASK_STATUSES,
  type WorkTask,
  type WorkTransport,
} from "../transport/transport";

/**
 * What the host can write for the open Task, so the controls it cannot answer are not offered
 * (RoomTransport.supportsTool/supportsCall): the mobile app answers update_task only with the completing
 * change, so the date and status choices, "Redigera" and "Återöppna" are gone there and "Markera klar"
 * stays; no steps, contacts or links are written either.
 */
export function useTaskOffers(
  transport: WorkTransport,
  task: WorkTask | undefined,
) {
  const offers = useToolSupport(transport);
  const dueOffered = offers("update_task", { changes: { due_at: null } });
  // The status chip lists every status, so it needs every one answered; "Återöppna" needs only "todo" from a done Task.
  const statusOffered = TASK_STATUSES.every((status) =>
    status === task?.status
      ? true
      : offers("update_task", {
          changes: { status },
          ...(task ? { from_status: task.status } : {}),
        }),
  );
  const reopenOffered = offers("update_task", {
    changes: { status: "todo" },
    from_status: "completed",
  });
  const doneOffered = offers("update_task", {
    changes: { status: "completed" },
  });
  const editOffered = offers("update_task", { changes: { title: "" } });
  // Deleting moves the Task to the trash and Ångra restores it, so both tools must be there.
  const trashOffered =
    offers("move_to_trash", { kind: "task" }) &&
    offers("restore_from_trash", { kind: "task" });
  // "Markera klar" completes; on a done Task the same place holds "Återöppna", which sets it back to "Att göra".
  const doneShown = task?.status === "completed" ? reopenOffered : doneOffered;
  // With the contacts room off a Task shows no Contacts, reads none and offers no link to one.
  const contactsOn = roomEnabled("contacts");
  const unlinkOffered =
    contactsOn &&
    offers("unlink_contact_from_task") &&
    offers("link_contact_to_task");
  return {
    offers,
    dueOffered,
    statusOffered,
    doneShown,
    editOffered,
    trashOffered,
    contactsOn,
    unlinkOffered,
  };
}
