import { useMemo } from "react";
import { useRead } from "../mcp-apps/ui/use-read";
import type { JournalLabels } from "./labels";
import type { JournalTransport } from "./transport";
import "./journal.css";

/** The titles of the entry's Tasks, by id; null for a Task whose title could not be read. */
type Titles = Record<string, string | null>;

/**
 * The Tasks linked to one entry, by name, as chips beside its Contacts and Projects. A chip
 * opens its Task when the host routes there (`onOpenTask`); otherwise it is the name only. The titles are read with
 * get_task once per entry; until they are there, and on a host that cannot read them, the line is the count
 * (the `tasks` label and the count), so the block never stands empty. A Task whose title could not be read shows a neutral name.
 */
export function EntryTasks({
  taskIds,
  labels: t,
  getTaskTitle,
  onOpenTask,
}: {
  taskIds: readonly string[];
  labels: JournalLabels;
  getTaskTitle?: JournalTransport["getTaskTitle"];
  onOpenTask?: (id: string) => void;
}) {
  // The ids as one value, so a new array with the same ids reads nothing again.
  const key = taskIds.join(",");
  const ids = useMemo(() => (key ? key.split(",") : []), [key]);
  const readTitles = useMemo(
    () =>
      getTaskTitle && ids.length > 0
        ? () =>
            Promise.all(
              ids.map((id) =>
                getTaskTitle(id).then(
                  (title): [string, string | null] => [id, title],
                  (): [string, string | null] => [id, null],
                ),
              ),
            ).then((pairs): Titles => Object.fromEntries(pairs))
        : undefined,
    [getTaskTitle, ids],
  );
  const [read] = useRead(readTitles);
  const titles = read.phase === "ready" ? read.value : undefined;

  if (taskIds.length === 0) return null;
  const known = titles && taskIds.every((id) => id in titles);
  if (!getTaskTitle || !known)
    return (
      <ul className="journal-list">
        <li>
          {t.tasks}: {taskIds.length}
        </li>
      </ul>
    );
  return (
    <ul className="journal-chips journal-task-chips" aria-label={t.tasks}>
      {taskIds.map((id) => {
        const title = titles[id];
        const name = title ?? t.taskChipFallback;
        return (
          <li key={id} className="journal-chip">
            {onOpenTask ? (
              <button
                type="button"
                className="journal-chip-name"
                title={name}
                aria-label={title ? t.openTaskNamed(title) : t.openLinkedTask}
                onClick={() => onOpenTask(id)}
              >
                {name}
              </button>
            ) : (
              <span className="journal-chip-name" title={name}>
                {name}
              </span>
            )}
          </li>
        );
      })}
    </ul>
  );
}
