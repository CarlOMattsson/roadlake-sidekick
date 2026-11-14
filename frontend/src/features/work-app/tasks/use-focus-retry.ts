import { useEffect, type RefObject } from "react";

/**
 * Puts focus on the `retry` of the write error row in the view that holds `anchor`, when `failed` becomes true:
 * the press that failed came from the controls above it, so the keyboard lands on the way to repeat it and not on the
 * page.
 */
export function useFocusRetry(
  failed: boolean,
  anchor: RefObject<HTMLElement | null>,
) {
  useEffect(() => {
    if (failed)
      anchor.current
        ?.closest("article")
        ?.querySelector<HTMLElement>(".sk-error--row .sk-error-retry")
        ?.focus();
  }, [failed, anchor]);
}
