import { useEffect, type MutableRefObject, type RefObject } from "react";
import type { FocusWanted } from "../board-writes";

/**
 * After a write the control that was asked for takes focus. A control is disabled while the write is
 * pending, so the effect waits until it is enabled. A card no longer on the board hands focus to the heading.
 * `changes` are the values whose change may have enabled it.
 */
export function useBoardFocus(
  focusWanted: MutableRefObject<FocusWanted | undefined>,
  root: RefObject<HTMLElement | null>,
  heading: RefObject<HTMLElement | null>,
  changes: unknown[],
) {
  useEffect(() => {
    const want = focusWanted.current;
    if (want === undefined) return;
    const card = Array.from(
      root.current?.querySelectorAll<HTMLElement>("[data-card-id]") ?? [],
    ).find((element) => element.dataset.cardId === want.id);
    const target = card?.querySelector<HTMLButtonElement>(
      want.kind === "more"
        ? ".work-card-head > :last-child"
        : ".work-drag-handle, .work-card-done",
    );
    if (card && target?.disabled) return;
    focusWanted.current = undefined;
    (target ?? heading.current)?.focus();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, changes);
}
