import { useEffect, useRef, useState } from "react";

/**
 * Whether a line-clamped text is cut where it is drawn: its full height is taller than the box that shows it. The answer
 * follows the box's size (ResizeObserver, which also reports once when it starts to observe), so "Visa mer" is offered on
 * a phone and not at a width where the whole text already fits. Before the first report, without ResizeObserver, or where
 * nothing is laid out (a box of no height), the answer is `undefined` and the caller falls back to its own guess.
 */
export function useCutText<T extends HTMLElement>(
  text: string | null | undefined,
) {
  const ref = useRef<T>(null);
  const [cut, setCut] = useState<boolean>();
  useEffect(() => {
    const node = ref.current;
    if (!node || typeof ResizeObserver === "undefined") return;
    const observer = new ResizeObserver(() =>
      setCut(
        node.clientHeight === 0
          ? undefined
          : node.scrollHeight > node.clientHeight + 1,
      ),
    );
    observer.observe(node);
    return () => observer.disconnect();
  }, [text]);
  return { ref, cut };
}
