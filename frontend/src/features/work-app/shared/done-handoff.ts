import { useEffect, useEffectEvent } from "react";
import type { AgendaUndo } from "../agenda/agenda-undo";
import type { WorkTask } from "../transport/transport";

/**
 * A Task marked done in its own view, which then goes back to the board it was opened from: the Task as the answer
 * left it, and its Ångra where the host can write the change back. The board shows the Task in its new place with
 * that Ångra, as after a move made on the board itself.
 */
export type DoneHandoff = { task: WorkTask; undo?: AgendaUndo };

// The boards on screen or kept mounted under the layer on top (the shell keeps every layer it shows again).
const boards = new Set<(done: DoneHandoff) => void>();
// A hand-off no board has taken yet: the board comes back with the Back that follows it.
let waiting: DoneHandoff | undefined;

/**
 * Hands `done` to the board the view goes back to. A board kept mounted below (the shell's layer) takes it at once;
 * otherwise the board mounted next takes it (a Back within the view mounts the board again).
 */
export function handOffDone(done: DoneHandoff) {
  const [board] = boards;
  if (board) board(done);
  else waiting = done;
}

/** Lets a board take what a Task view hands it (see handOffDone). */
export function useDoneHandoff(take: (done: DoneHandoff) => void) {
  const onDone = useEffectEvent(take);
  useEffect(() => {
    const board = (done: DoneHandoff) => onDone(done);
    boards.add(board);
    const done = waiting;
    waiting = undefined;
    if (done) board(done);
    return () => {
      boards.delete(board);
    };
  }, []);
}
