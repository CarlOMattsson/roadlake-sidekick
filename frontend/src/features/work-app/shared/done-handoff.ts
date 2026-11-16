import { useEffect, useEffectEvent } from "react";
import type { AgendaUndo } from "../agenda/agenda-undo";
import type { WorkTask } from "../transport/transport";

/**
 * A Task marked done in its own view, which then goes back to the list it was opened from: the Task as the answer
 * left it, and its Ångra where the host can write the change back. The list shows the Task with that Ångra on its
 * row, as after the same change made in the list itself.
 */
export type DoneHandoff = { task: WorkTask; undo?: AgendaUndo };

/** The lists that take a Task marked done in its own view: the board and the agenda. */
export type DoneList = "board" | "agenda";

/** Whether `kind` (a frame kind, or the list a shell layer was opened from) is a list that takes a hand-off. */
export function takesDone(kind: string | undefined): kind is DoneList {
  return kind === "board" || kind === "agenda";
}

// The lists on screen or kept mounted under the layer on top (the shell keeps every layer it shows again), newest last.
const lists = new Set<{ kind: DoneList; take: (done: DoneHandoff) => void }>();
// A hand-off no list has taken yet: the list comes back with the Back that follows it.
let waiting: { kind: DoneList; done: DoneHandoff } | undefined;

/**
 * Hands `done` to the list of `kind` the view goes back to. A list kept mounted below (the shell's layer) takes it at
 * once, the one mounted last when there are more; otherwise the list of that kind mounted next takes it (a Back within
 * the view mounts the list again).
 */
export function handOffDone(kind: DoneList, done: DoneHandoff) {
  const below = [...lists].findLast((list) => list.kind === kind);
  if (below) below.take(done);
  else waiting = { kind, done };
}

/** Lets a list of `kind` take what a Task view hands it (see handOffDone). */
export function useDoneHandoff(
  kind: DoneList,
  take: (done: DoneHandoff) => void,
) {
  const onDone = useEffectEvent(take);
  useEffect(() => {
    const list = { kind, take: (done: DoneHandoff) => onDone(done) };
    lists.add(list);
    if (waiting?.kind === kind) {
      const { done } = waiting;
      waiting = undefined;
      list.take(done);
    }
    return () => {
      lists.delete(list);
    };
  }, [kind]);
}
