import { useEffect, useMemo, useState } from "react";
import type { JournalLabels } from "./labels";
import type { JournalTransport } from "./transport";
import "./journal.css";

/** The titles of the entry's Tasks, by id; null for a Task whose title could not be read. */
type Titles = Record<string, string | null>;

/**
 * The Tasks linked to one entry, by name, as chips beside its Contacts and Projects. A chip
 * opens its Task when the host routes there (`onOpenTask`); otherwise it is the name only. The titles are read with
 * get_task once per entry; until they are there, and on a host that cannot read them, the line is the count
 * ("Uppgifter: 2"), so the block never stands empty. A Task whose title could not be read shows a neutral name.
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
  const [titles, setTitles] = useState<Titles>();
  // The ids as one value, so a new array with the same ids reads nothing again.
  const key = taskIds.join(",");
  const ids = useMemo(() => (key ? key.split(",") : []), [key]);
  useEffect(() => {
    if (!getTaskTitle || ids.length === 0) return undefined;
    let live = true;
    void Promise.all(
      ids.map((id) =>
        getTaskTitle(id).then(
          (title): [string, string | null] => [id, title],
          (): [string, string | null] => [id, null],
        ),
      ),
    ).then((pairs) => {
      if (live) setTitles(Object.fromEntries(pairs));
    });
    return () => {
      live = false;
    };
  }, [getTaskTitle, ids]);

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
        const name = titles[id] ?? t.taskChipFallback;
        return (
          <li key={id} className="journal-chip">
            {onOpenTask ? (
              <button
                type="button"
                className="journal-chip-name"
                title={name}
                aria-label={t.openTaskNamed(name)}
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
