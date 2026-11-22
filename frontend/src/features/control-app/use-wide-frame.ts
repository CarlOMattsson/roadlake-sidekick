import { useCallback, useSyncExternalStore, type RefObject } from "react";

/** The frame width, in rem, from which a view draws a table instead of rows (desktop spec 1: 48rem is 768 at 100 %). */
export const TABLE_FROM_REM = 48;

/**
 * Whether the app frame around `ref` is at least `rem` wide. It is the answer of the container query
 * `@container sk-frame (min-width: 48rem)`, asked of the DOM, because a table is other markup than a row and CSS alone
 * cannot swap one for the other. The frame is the nearest `.sk-frame`; with none (a card mounted on its own) the element
 * itself. False where nothing can be measured (a test, a hidden pane), which is the row layout of a phone.
 */
export function useFrameAtLeast(
  ref: RefObject<HTMLElement | null>,
  rem: number = TABLE_FROM_REM,
): boolean {
  const measure = useCallback(() => {
    const element = ref.current;
    if (!element) return false;
    const frame = element.closest<HTMLElement>(".sk-frame") ?? element;
    const root = Number.parseFloat(
      getComputedStyle(document.documentElement).fontSize,
    );
    return frame.getBoundingClientRect().width >= rem * (root || 16);
  }, [ref, rem]);
  const subscribe = useCallback(
    (notify: () => void) => {
      const element = ref.current;
      const frame = element?.closest<HTMLElement>(".sk-frame") ?? element;
      window.addEventListener("resize", notify);
      const observer =
        frame && typeof ResizeObserver !== "undefined"
          ? new ResizeObserver(notify)
          : undefined;
      if (frame) observer?.observe(frame);
      return () => {
        window.removeEventListener("resize", notify);
        observer?.disconnect();
      };
    },
    [ref],
  );
  return useSyncExternalStore(subscribe, measure, () => false);
}
