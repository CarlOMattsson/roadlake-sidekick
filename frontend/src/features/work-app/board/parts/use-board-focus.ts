import { useEffect, type MutableRefObject, type RefObject } from "react";
import type { FocusWanted } from "../board-writes";

/**
 * After a write the control that was asked for takes focus. A control is disabled while the write is
 * pending, so the effect waits until it is enabled. A card no longer on the board hands focus to the heading.
 * `enabledBy` are the board's values whose change may have enabled the control; the effect runs again when one changes.
 */
export function useBoardFocus(
  wantedRef: MutableRefObject<FocusWanted | undefined>,
  rootRef: RefObject<HTMLElement | null>,
  headingRef: RefObject<HTMLElement | null>,
  enabledBy: {
    page: unknown;
    preview: unknown;
    busy: unknown;
    undos: unknown;
  },
) {
  const { page, preview, busy, undos } = enabledBy;
  useEffect(() => {
    const want = wantedRef.current;
    if (want === undefined) return;
    const card = Array.from(
      rootRef.current?.querySelectorAll<HTMLElement>("[data-card-id]") ?? [],
    ).find((element) => element.dataset.cardId === want.id);
    const target = card?.querySelector<HTMLButtonElement>(
      want.kind === "more"
        ? ".work-card-head > :last-child"
        : ".work-drag-handle, .work-card-done",
    );
    if (card && target?.disabled) return;
    wantedRef.current = undefined;
    (target ?? headingRef.current)?.focus();
    // `page`, `preview`, `busy` and `undos` are not read inside: they are the triggers that run the effect again.
  }, [wantedRef, rootRef, headingRef, page, preview, busy, undos]);
}
