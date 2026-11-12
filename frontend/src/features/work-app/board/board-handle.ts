import type {
  KeyboardEvent,
  PointerEvent as ReactPointerEvent,
  RefObject,
} from "react";
import type {
  BoardDragEvent,
  BoardDragState,
  BoardGeometry,
} from "./board-drag";
import { pointerKind } from "./board-geometry";
import type { WorkItemRecord } from "../transport/transport";

/** What a card's drag handle reads and calls: the board's drag state, its geometry and its drag and step actions. */
export type DragHandleContext = {
  disabled: boolean;
  dragRef: RefObject<BoardDragState>;
  measure: () => BoardGeometry | undefined;
  dragEvent: (event: BoardDragEvent) => void;
  startTicks: () => void;
  step: (card: WorkItemRecord, direction: -1 | 1) => void;
};

/** The drag handle's pointer and key handlers for one card. */
export function dragHandle(
  {
    disabled,
    dragRef,
    measure,
    dragEvent,
    startTicks,
    step,
  }: DragHandleContext,
  item: WorkItemRecord,
) {
  return {
    onPointerDown(event: ReactPointerEvent<HTMLButtonElement>) {
      if (disabled || event.button !== 0 || dragRef.current.phase !== "idle")
        return;
      const board = measure();
      if (!board) return;
      event.currentTarget.setPointerCapture(event.pointerId);
      event.currentTarget.focus();
      dragEvent({
        type: "down",
        taskId: item.id,
        point: { x: event.clientX, y: event.clientY },
        time: performance.now(),
        pointerType: pointerKind(event.pointerType),
        board,
      });
      startTicks();
    },
    onPointerMove(event: ReactPointerEvent<HTMLButtonElement>) {
      if (dragRef.current.phase === "idle") return;
      const board = measure();
      if (!board) return;
      dragEvent({
        type: "move",
        point: { x: event.clientX, y: event.clientY },
        time: performance.now(),
        board,
      });
    },
    onPointerUp(event: ReactPointerEvent<HTMLButtonElement>) {
      if (dragRef.current.phase === "idle") return;
      const board = measure();
      if (!board) return;
      dragEvent({
        type: "up",
        point: { x: event.clientX, y: event.clientY },
        time: performance.now(),
        board,
      });
    },
    onPointerCancel() {
      dragEvent({ type: "escape" });
    },
    onKeyDown(event: KeyboardEvent<HTMLButtonElement>) {
      if (event.key === "Escape" && dragRef.current.phase !== "idle") {
        event.preventDefault();
        dragEvent({ type: "escape" });
        return;
      }
      if (event.key !== "ArrowLeft" && event.key !== "ArrowRight") return;
      event.preventDefault();
      if (!disabled && dragRef.current.phase === "idle")
        step(item, event.key === "ArrowLeft" ? -1 : 1);
    },
  };
}
