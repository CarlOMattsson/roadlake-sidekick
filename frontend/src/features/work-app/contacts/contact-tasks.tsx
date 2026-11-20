import { useEffect, useId, useMemo, useRef, useState } from "react";
import { PlusIcon } from "../../mcp-apps/ui/icons";
import { newTaskInputLabelsFor } from "../tasks/new-task-input-labels";
import { NewTaskInput } from "../tasks/new-task-input";
import { TaskSummaryList } from "../tasks/task-summary-list";
import type { WorkLabels } from "../shared/labels";
import type { WorkTaskSummary } from "../transport/transport";
import type { FrameProps } from "../view/parts/frame-types";
import { contactsRoomLabelsFor } from "./contacts-room-labels";
import { tasksByUrgency } from "./contacts-sections";

/**
 * A Contact's Tasks, and the way to add one for her: with Tasks the heading carries a + (44) that opens the Work create
 * field under it; with none, the section is left out (design system §3, Tomt) and one action row stands where it
 * would. The Task is made with the Contact linked, and the field stays open for the next one, as in Work. `canCreate`
 * is false for an archived Contact, an open editor, or a host without create_task: nothing is offered then.
 */
export function ContactTasks({
  contactId,
  firstName,
  tasks,
  labels: t,
  transport,
  onOpen,
  onReload,
  canCreate,
  reloading,
}: Pick<FrameProps, "transport" | "onOpen"> & {
  contactId: string;
  /** The first word of her name, for "New task for Anna". */
  firstName: string;
  tasks: WorkTaskSummary[];
  labels: WorkLabels;
  /** Reads the Contact's Tasks again; called when a Task is made, so it shows in the list. */
  onReload: () => void;
  canCreate: boolean;
  /** True while the frame reads the Contact again; the frame then moves the focus to its heading. */
  reloading: boolean;
}) {
  const [open, setOpen] = useState(false);
  const shown = open && canCreate;
  const fieldId = useId();
  const wrap = useRef<HTMLDivElement>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const giveBack = useRef(false);
  const hadFocus = useRef(false);
  const words = contactsRoomLabelsFor(t.dateLocale);
  const name = words.newTaskFor(firstName);
  // One object per Contact, so the field's idempotency signature and its calls do not change with every render.
  const fields = useMemo(() => ({ contact_ids: [contactId] }), [contactId]);

  // Esc and × close the field: the focus goes back to the + (or the row) that opened it, once it is drawn again.
  useEffect(() => {
    if (giveBack.current && !shown) {
      giveBack.current = false;
      trigger.current?.focus();
    }
  }, [shown]);
  // The frame focuses its heading when it has read the Contact again: a Task typed in a row keeps the field's focus.
  useEffect(() => {
    if (reloading) {
      hadFocus.current = Boolean(
        wrap.current?.contains(document.activeElement),
      );
      return;
    }
    if (hadFocus.current) {
      hadFocus.current = false;
      wrap.current?.querySelector("input")?.focus();
    }
  }, [reloading]);

  const start = (
    <button
      ref={trigger}
      type="button"
      className={tasks.length > 0 ? "sk-iconbtn" : "work-add-row sk-action-row"}
      aria-label={tasks.length > 0 ? name : undefined}
      aria-expanded={shown}
      aria-controls={fieldId}
      onClick={() => setOpen(true)}
    >
      <PlusIcon />
      {tasks.length === 0 && name}
    </button>
  );
  return (
    <>
      {tasks.length > 0 && (
        <div className="work-contact-tasks-head">
          <h3>{t.tasks}</h3>
          {canCreate && start}
        </div>
      )}
      {tasks.length === 0 && canCreate && !shown && start}
      {canCreate && (
        <div ref={wrap} className="work-contact-task-new">
          <NewTaskInput
            id={fieldId}
            transport={transport}
            labels={newTaskInputLabelsFor(t.dateLocale)}
            workLabels={t}
            fields={fields}
            open={shown}
            onClose={() => {
              setOpen(false);
              giveBack.current = true;
            }}
            onCreated={onReload}
          />
        </div>
      )}
      {tasks.length > 0 && (
        <TaskSummaryList
          tasks={tasksByUrgency(tasks)}
          labels={t}
          empty={t.noTasks}
          onOpen={onOpen}
          transport={transport}
          onReload={onReload}
        />
      )}
    </>
  );
}
