import type { BoardGeometry, DragPointer } from "./board-drag";

function rectOf(element: Element) {
  const { left, top, width, height } = element.getBoundingClientRect();
  return { left, top, width, height };
}

export function pointerKind(type: string): DragPointer {
  return type === "touch" || type === "pen" ? type : "mouse";
}

/** The board's geometry in viewport pixels, read from the DOM when the event happens. */
export function measureBoard(
  root: HTMLElement | null,
): BoardGeometry | undefined {
  if (!root) return undefined;
  const columns = Array.from(
    root.querySelectorAll<HTMLElement>("[data-board-column]"),
    (column) => ({
      id: column.dataset.boardColumn ?? "",
      rect: rectOf(column),
      cards: Array.from(
        column.querySelectorAll<HTMLElement>("[data-card-id]"),
        (card) => ({ id: card.dataset.cardId ?? "", rect: rectOf(card) }),
      ),
    }),
  );
  return { rect: rectOf(root), columns };
}
