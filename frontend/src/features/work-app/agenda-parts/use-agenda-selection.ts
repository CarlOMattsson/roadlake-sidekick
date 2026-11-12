import { useState, type RefObject } from "react";
import { useShortcuts } from "../../mcp-apps/ui/shortcuts";
import {
  TASK_STATUSES,
  type TaskStatusValue,
  type WorkItemRecord,
} from "../transport";
import { cardKey } from "../work-items";

/**
 * The record the keys have selected and the window keys that move it: j and k step through the records, x toggles done
 * of the selected Task, 1 to 4 set its status. Only a fullscreen caller turns the keys on (`shortcuts`), and not in the
 * waiting view.
 */
export function useAgendaSelection({
  stepping,
  root,
  enabled,
  current,
  statusOffered,
  write,
  toggleDone,
}: {
  /** The records j and k step through, in the order they are shown. */
  stepping: WorkItemRecord[];
  root: RefObject<HTMLElement | null>;
  enabled: boolean;
  current: (item: WorkItemRecord) => WorkItemRecord;
  statusOffered: (status: TaskStatusValue, from?: string) => boolean;
  write: (record: WorkItemRecord, to: TaskStatusValue) => void;
  toggleDone: (record: WorkItemRecord) => void;
}) {
  const [selected, setSelected] = useState<string>();
  const selectedItem = stepping.find((item) => cardKey(item) === selected);

  /** Moves the selection to a row and gives that row focus, so keys and focus agree. */
  function select(key: string) {
    setSelected(key);
    const rows = Array.from(
      root.current?.querySelectorAll<HTMLElement>("[data-agenda-key]") ?? [],
    );
    const row = rows.find((element) => element.dataset.agendaKey === key);
    if (!row) return;
    row.focus();
    row.scrollIntoView?.({ block: "nearest" });
  }
  function step(delta: number) {
    if (stepping.length === 0) return;
    const index = stepping.findIndex((item) => cardKey(item) === selected);
    const last = stepping.length - 1;
    const next =
      index === -1
        ? delta > 0
          ? 0
          : last
        : Math.min(Math.max(index + delta, 0), last);
    const target = stepping[next];
    if (target) select(cardKey(target));
  }
  function setSelectedStatus(to: TaskStatusValue) {
    if (
      selectedItem?.kind !== "task" ||
      !statusOffered(to, current(selectedItem).status)
    )
      return;
    if (current(selectedItem).status === to) return;
    write(selectedItem, to);
  }

  useShortcuts(
    {
      j: () => step(1),
      k: () => step(-1),
      x: () => {
        if (selectedItem?.kind !== "task") return;
        const from = current(selectedItem).status;
        if (statusOffered(from === "completed" ? "todo" : "completed", from))
          toggleDone(selectedItem);
      },
      "1": () => setSelectedStatus(TASK_STATUSES[0]),
      "2": () => setSelectedStatus(TASK_STATUSES[1]),
      "3": () => setSelectedStatus(TASK_STATUSES[2]),
      "4": () => setSelectedStatus(TASK_STATUSES[3]),
    },
    { enabled },
  );

  return { selected };
}
