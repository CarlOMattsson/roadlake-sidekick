import { useContext } from "react";
import { PlusIcon } from "../mcp-apps/ui/icons";
import { RoomMessageContext } from "../mcp-apps/ui/room-context";
import { EmptyState } from "../mcp-apps/ui/states";
import { WorkNewTaskContext } from "./empty-actions";
import type { WorkLabels } from "./labels";

/**
 * The empty Agenda and Status, in the family's empty state as Contacts and Journal have it: what is missing,
 * one line on what the view is for, "Säg till Claude:" with an example (a button that sends it where the host offers
 * messages), and "+ Lägg till en uppgift" where the tab row can create a Task.
 */
export function WorkEmpty({
  title,
  hint,
  labels: t,
}: {
  title: string;
  hint: string;
  labels: WorkLabels;
}) {
  const send = useContext(RoomMessageContext);
  const newTask = useContext(WorkNewTaskContext);
  const example = t.workEmptyAsk;
  return (
    <EmptyState
      title={title}
      hint={hint}
      ask={{
        locale: t.dateLocale,
        example,
        onSend: send ? () => void send(example) : undefined,
      }}
    >
      {newTask && (
        <button
          type="button"
          className="work-add-row sk-action-row"
          onClick={newTask}
        >
          <PlusIcon />
          {t.emptyAddTask}
        </button>
      )}
    </EmptyState>
  );
}
