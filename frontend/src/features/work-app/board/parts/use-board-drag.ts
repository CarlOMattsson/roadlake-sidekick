import {
  useEffect,
  useEffectEvent,
  useRef,
  useState,
  type RefObject,
} from "react";
import {
  initialBoardDrag,
  reduceBoardDrag,
  type BoardDragEvent,
  type BoardDragState,
  type BoardMove,
} from "../board-drag";
import { measureBoard } from "../board-geometry";
import { dragHandle } from "../board-handle";
import type { ReorderTo } from "../board-columns";
import {
  TASK_STATUSES,
  isTaskStatus,
  type TaskStatusValue,
  type WorkItemRecord,
} from "../../transport/transport";

/** How often a drag is re-evaluated while the pointer is still: long press and edge dwell. */
const DRAG_TICK_MS = 50;

type Options = {
  boardRoot: RefObject<HTMLElement | null>;
  single: boolean;
  disabled: boolean;
  move: (card: WorkItemRecord, to: TaskStatusValue, shown?: boolean) => void;
  reorder: (status: TaskStatusValue, taskId: string, to: ReorderTo) => void;
  taskCard: (id: string) => WorkItemRecord | undefined;
};

/** The drag of a card handle: the reducer's state, its ticks, and the move or order write a drop starts. */
export function useBoardDrag({
  boardRoot,
  single,
  disabled,
  move,
  reorder,
  taskCard,
}: Options) {
  // The ref is what the pure reducer reads; the state only repaints it.
  const dragRef = useRef<BoardDragState>(initialBoardDrag);
  const [drag, setDrag] = useState<BoardDragState>(initialBoardDrag);
  const ticks = useRef<ReturnType<typeof setInterval> | undefined>(undefined);
  useEffect(
    () => () => {
      if (ticks.current) clearInterval(ticks.current);
    },
    [],
  );
  const measure = () => measureBoard(boardRoot.current);
  /** Feeds one event to the drag reducer; a drag that ends on another status starts the write. */
  function dragEvent(event: BoardDragEvent) {
    const next = reduceBoardDrag(dragRef.current, event);
    if (next.phase !== "ended") {
      dragRef.current = next;
      setDrag(next);
      return;
    }
    dragRef.current = initialBoardDrag;
    setDrag(initialBoardDrag);
    stopTicks();
    if (next.outcome.type === "move") drop(next.outcome.move);
  }
  function startTicks() {
    if (ticks.current) return;
    ticks.current = setInterval(() => {
      const board = measure();
      if (board) dragEvent({ type: "tick", time: performance.now(), board });
    }, DRAG_TICK_MS);
  }
  function stopTicks() {
    if (ticks.current) clearInterval(ticks.current);
    ticks.current = undefined;
  }
  /**
   * A drop on another Task status is a status write. A drop inside its own column is an order write
   * for that column (see `reorder`); a column that is not a Task status takes no drop.
   */
  function drop(next: BoardMove) {
    if (!isTaskStatus(next.toColumn)) return;
    if (next.toColumn === next.fromColumn) {
      reorder(next.toColumn, next.taskId, next.toIndex);
      return;
    }
    const card = taskCard(next.taskId);
    if (card) move(card, next.toColumn, true);
  }
  /** Arrow keys move a Task to the neighbouring status; the first and last status stop it. */
  function step(card: WorkItemRecord, direction: -1 | 1) {
    const at = TASK_STATUSES.indexOf(card.status as TaskStatusValue);
    const next = TASK_STATUSES[at + direction];
    if (at === -1 || next === undefined) return;
    move(card, next, true);
  }
  /** The drag handle's pointer and key handlers for one card. */
  function handleFor(item: WorkItemRecord) {
    return dragHandle(
      { disabled, dragRef, measure, dragEvent, startTicks, step },
      item,
    );
  }
  // A drag cannot go on once the board turns single: there is no handle to hold.
  const escapeDrag = useEffectEvent(() => {
    if (dragRef.current.phase !== "idle") dragEvent({ type: "escape" });
  });
  useEffect(() => {
    if (single) escapeDrag();
  }, [single]);

  return { drag, handleFor };
}
