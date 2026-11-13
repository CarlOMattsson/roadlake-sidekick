import { useId, useRef, useState } from "react";
import { useToolSupport } from "../../mcp-apps/tool-support";
import { ChevronDownIcon, ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { KeyScope } from "../../mcp-apps/ui/key-scope";
import {
  placeChanges,
  placeOf,
  placeTitle,
  useGroupChoices,
  type TaskPlace as Place,
} from "../hierarchy/group-choices";
import { GroupSelect } from "../hierarchy/group-select";
import { groupSelectLabelsFor } from "../hierarchy/group-select-labels";
import type { WorkLabels } from "../shared/labels";
import { taskPlaceLabelsFor } from "./task-place-labels";
import { TaskPriority } from "./task-priority";
import { TaskRepeat } from "./task-repeat";
import type {
  WorkFrame,
  WorkTask,
  WorkTaskChanges,
  WorkTransport,
} from "../transport/transport";

/**
 * The Task's place, repeat rule and priority, one row of chips under the date and status chips (design system §3,
 * property chip).
 * "Plats: Renovering av köket ⌄" says where the Task belongs (a Project, a Process, a Domain or "Att sortera"); a
 * tap opens a panel with the place picker, and a choice is one update_task through `onChoose`. The same panel holds
 * "Öppna Renovering av köket ›" for a Project or Process. Where the host cannot write the place (the phone), the
 * panel keeps only the open link, and a place with neither is plain text. The repeat rule (TaskRepeat) and the priority
 * (TaskPriority) are the Task's own chips next to it: a picker where the host can write, a read-only chip where it
 * cannot.
 * Escape closes the panel and returns focus to the chip.
 */
export function TaskPlace({
  task,
  transport,
  labels: t,
  busy,
  projectOpenable,
  onChoose,
  onOpen,
}: {
  task: WorkTask;
  transport: WorkTransport;
  labels: WorkLabels;
  busy: boolean;
  /** False when the host cannot answer get_project: a Project is then not offered as a link. */
  projectOpenable: boolean;
  onChoose: (changes: WorkTaskChanges) => void;
  onOpen: (frame: WorkFrame, label?: string) => void;
}) {
  const offers = useToolSupport(transport);
  const words = taskPlaceLabelsFor(t.dateLocale);
  const [open, setOpen] = useState(false);
  // Set by the first opening, so the places are read once and kept (useGroupChoices).
  const [opened, setOpened] = useState(false);
  const panelId = useId();
  const chip = useRef<HTMLButtonElement>(null);
  const place = placeOf(task);
  const carriedTitle =
    place?.kind === "project" ? (task.project_title ?? undefined) : undefined;
  // A Project's name comes with the Task (get_task); a Domain's or Process's is found among the places, which are then read.
  const choices = useGroupChoices(
    transport,
    opened || (place !== null && place.kind !== "project"),
  );
  const title =
    carriedTitle ??
    (choices.phase === "ready"
      ? placeTitle(choices.domains, place)
      : undefined);
  const name = place
    ? (title ?? fallbackName(place, words))
    : words.unsortedName;
  const writable =
    offers("update_task", { changes: placeChanges(place) }) &&
    offers("get_work_hierarchy");
  // The Project or Process page the panel links to; a Domain has no page of its own.
  const target =
    place?.kind === "project" && projectOpenable
      ? ({ kind: "project", id: place.id } as const)
      : place?.kind === "process" && offers("get_process")
        ? ({ kind: "process", id: place.id } as const)
        : null;
  const interactive = writable || target !== null;
  const repeatWritable = offers("update_task", {
    changes: { recurrence: null },
  });
  const priorityWritable = offers("update_task", {
    changes: { priority: "normal" },
  });

  function close(refocus: boolean) {
    setOpen(false);
    if (refocus) chip.current?.focus();
  }
  function choose(next: Place | null) {
    if (next?.kind === place?.kind && next?.id === place?.id) return;
    close(false);
    onChoose(placeChanges(next));
  }

  return (
    <KeyScope
      className="work-task-props work-task-place"
      onEscape={open ? () => close(true) : undefined}
    >
      {interactive ? (
        <button
          ref={chip}
          type="button"
          className="sk-chip work-prop-chip"
          aria-label={`${words.changePlace}: ${name}`}
          aria-expanded={open}
          aria-controls={open ? panelId : undefined}
          disabled={busy}
          onClick={() => {
            setOpen(!open);
            setOpened(true);
          }}
        >
          <span>{words.chipValue(name)}</span>
          <ChevronDownIcon size={16} />
        </button>
      ) : (
        <span className="sk-chip work-prop-chip work-prop-static">
          <span>{words.chipValue(name)}</span>
        </span>
      )}
      <TaskRepeat
        rule={task.recurrence}
        title={task.title}
        words={words}
        writable={repeatWritable}
        busy={busy}
        onChoose={onChoose}
      />
      <TaskPriority
        task={task}
        labels={t}
        writable={priorityWritable}
        busy={busy}
        onChoose={onChoose}
      />
      {interactive && open && (
        <div
          id={panelId}
          role="group"
          aria-label={words.changePlace}
          className="work-place-panel"
        >
          {writable && (
            <GroupSelect
              label={words.pickerFor(task.title)}
              value={place}
              choices={choices}
              labels={groupSelectLabelsFor(t.dateLocale)}
              disabled={busy}
              onChange={choose}
            />
          )}
          {target && (
            <button
              type="button"
              className="sk-btn--open work-place-open"
              onClick={() =>
                onOpen({ kind: target.kind, id: target.id }, title)
              }
            >
              {words.open(name)}
              <ChevronRightIcon />
            </button>
          )}
        </div>
      )}
    </KeyScope>
  );
}

/** The word shown while a place's own name cannot be read. */
function fallbackName(
  place: Place,
  words: ReturnType<typeof taskPlaceLabelsFor>,
): string {
  if (place.kind === "project") return words.projectName;
  if (place.kind === "process") return words.processName;
  return words.domainName;
}
