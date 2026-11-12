import type { WorkLabels } from "../../shared/labels";
import type { RoomTarget } from "../../../mcp-apps/room-types";
import type { WorkFrame } from "../../transport/transport";

/** The list view a record is opened from ("agenda", "board" or "hierarchy"), or undefined when `frame` is no list. */
function listViewOf(frame: WorkFrame | undefined): string | undefined {
  return frame?.kind === "agenda" ||
    frame?.kind === "board" ||
    frame?.kind === "hierarchy"
    ? frame.kind
    : undefined;
}

/**
 * Where a frame belongs on the shell's stack: a Task, a Project or a Process in Work, a Contact in Contacts. Other
 * frames (the Contact list, cards) are not records and stay in the view. `label` is the name the caller
 * knows (a Task's or Contact's title); without it the name the frame carries is used, if any. `from` is the frame
 * the record is opened from: a list there names the Back header ("‹ Projekt" from the Projects tab) when the
 * record it returns to has no name of its own.
 */
export function routeOfFrame(
  frame: WorkFrame,
  label?: string,
  from?: WorkFrame,
): RoomTarget | undefined {
  const list = listViewOf(from);
  const origin = list === undefined ? {} : { from: list };
  switch (frame.kind) {
    case "task":
      return {
        room: "work",
        view: "task",
        id: frame.id,
        label: label ?? frame.task?.title,
        ...origin,
      };
    case "project":
      return {
        room: "work",
        view: "project",
        id: frame.id,
        label: label ?? frame.project?.title,
        ...origin,
      };
    case "process":
      return {
        room: "work",
        view: "process",
        id: frame.id,
        label: label ?? frame.process?.name,
        ...origin,
      };
    case "contact":
      return {
        room: "contacts",
        view: "contact",
        id: frame.id,
        label: label ?? frame.context?.contact.display_name,
      };
    case "compact":
      return {
        room: "contacts",
        view: "contact",
        id: frame.contact.id,
        label: frame.contact.display_name,
      };
    default:
      return undefined;
  }
}

/** The name of the view one step below, for the Back header: "Tavla", "Agenda", "Kontakter" or the kind word. */
export function parentLabel(
  frame: WorkFrame | undefined,
  t: WorkLabels,
): string {
  switch (frame?.kind) {
    case "board":
      return t.board;
    case "agenda":
      return t.agenda;
    case "hierarchy":
      return t.hierarchy;
    case "contacts":
      return t.contacts;
    case "task":
      return t.task;
    case "project":
      return t.project;
    case "process":
      return t.kindName.process;
    case "contact":
      return t.contact;
    default:
      return t.title;
  }
}

/**
 * The key of a list frame for its scroll memory: a board per segment, the agenda and the Contact
 * list. Other frames have no list to return to, so they have no key.
 */
export function listScrollKey(
  frame: WorkFrame | undefined,
): string | undefined {
  if (frame?.kind === "board") return `board:${frame.column ?? ""}`;
  if (frame?.kind === "agenda" || frame?.kind === "contacts") return frame.kind;
  return undefined;
}
