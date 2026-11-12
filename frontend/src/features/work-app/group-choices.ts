import { useEffect, useRef, useState } from "react";
import type {
  WorkHierarchyNode,
  WorkTaskChanges,
  WorkTransport,
} from "./transport";

/**
 * Where a Task belongs: one Domain, one Project or one Process, or nowhere (null, the To sort list). A Task has at
 * most one of the three (the server refuses two), so a move names one and clears the other two.
 */
export type TaskPlace = { kind: "domain" | "project" | "process"; id: string };

/** One Project or Process a Task can be placed in. */
export type GroupChoice = {
  kind: "project" | "process";
  id: string;
  title: string;
  status?: string;
};

/** One Domain with the open Projects and Processes under it, in the server's order. */
export type DomainChoices = {
  id: string;
  title: string;
  accent?: string | null;
  groups: GroupChoice[];
};

/**
 * The places of the hierarchy a Task can be moved to: each Domain with its open Projects (completed ones are left
 * out) and its Processes (archived ones are left out), Projects first. A Project or Process whose Domain is not on
 * the page is left out too.
 */
export function domainChoices(nodes: WorkHierarchyNode[]): DomainChoices[] {
  const domains = nodes.filter((node) => node.kind === "domain");
  const open = (node: WorkHierarchyNode) =>
    node.status !== "completed" && node.status !== "archived";
  return domains.map((domain) => {
    const under = (kind: "project" | "process") =>
      nodes
        .filter(
          (node) =>
            node.kind === kind && node.parent_id === domain.id && open(node),
        )
        .map((node) => ({
          kind,
          id: node.id,
          title: node.title,
          status: node.status,
        }));
    return {
      id: domain.id,
      title: domain.title,
      accent: domain.accent,
      groups: [...under("project"), ...under("process")],
    };
  });
}

/** The update_task changes that move a Task to `place`: the named field set, the other two cleared. */
export function placeChanges(place: TaskPlace | null): WorkTaskChanges {
  return {
    domain_id: place?.kind === "domain" ? place.id : null,
    project_id: place?.kind === "project" ? place.id : null,
    process_id: place?.kind === "process" ? place.id : null,
  };
}

/** The place a Task is in now, from its three fields; null when it has none. */
export function placeOf(task: {
  project_id?: string | null;
  process_id?: string | null;
  domain_id?: string | null;
}): TaskPlace | null {
  if (task.project_id) return { kind: "project", id: task.project_id };
  if (task.process_id) return { kind: "process", id: task.process_id };
  if (task.domain_id) return { kind: "domain", id: task.domain_id };
  return null;
}

/** A place as one option value ("project:<id>"), and back; "" is no place. */
export function placeValue(place: TaskPlace | null): string {
  return place ? `${place.kind}:${place.id}` : "";
}

export function placeFromValue(value: string): TaskPlace | null {
  const [kind, id] = value.split(":", 2);
  if (!id || (kind !== "domain" && kind !== "project" && kind !== "process"))
    return null;
  return { kind, id };
}

/** The title of a place among the choices (a Domain, Project or Process), or undefined when it is not there. */
export function placeTitle(
  choices: readonly DomainChoices[],
  place: TaskPlace | null,
): string | undefined {
  if (!place) return undefined;
  for (const domain of choices) {
    if (place.kind === "domain" && domain.id === place.id) return domain.title;
    const group = domain.groups.find(
      (item) => item.kind === place.kind && item.id === place.id,
    );
    if (group) return group.title;
  }
  return undefined;
}

export type GroupChoicesState =
  | { phase: "idle" | "loading" }
  | { phase: "error" }
  | { phase: "ready"; domains: DomainChoices[] };

/**
 * Reads the places once (get_work_hierarchy without Tasks) the first time `enabled` is true, and keeps them; a failed
 * read stays failed until `retry`. Nothing is read while `enabled` is false, so a closed picker costs no call.
 */
export function useGroupChoices(
  transport: WorkTransport,
  enabled: boolean,
): GroupChoicesState & { retry: () => void } {
  const [answer, setAnswer] = useState<GroupChoicesState>();
  const [attempt, setAttempt] = useState(0);
  // The attempt whose read has started; a second render with the same attempt reads nothing.
  const started = useRef<number | null>(null);
  const alive = useRef(true);
  useEffect(() => {
    alive.current = true;
    return () => {
      alive.current = false;
    };
  }, []);
  useEffect(() => {
    if (!enabled || started.current === attempt) return;
    started.current = attempt;
    transport.getWorkHierarchy().then(
      (frame) => {
        if (alive.current)
          setAnswer({ phase: "ready", domains: domainChoices(frame.nodes) });
      },
      () => {
        if (alive.current) setAnswer({ phase: "error" });
      },
    );
  }, [enabled, transport, attempt]);
  const state: GroupChoicesState = answer ?? {
    phase: enabled ? "loading" : "idle",
  };
  return {
    ...state,
    retry: () => {
      setAnswer(undefined);
      setAttempt((n) => n + 1);
    },
  };
}
