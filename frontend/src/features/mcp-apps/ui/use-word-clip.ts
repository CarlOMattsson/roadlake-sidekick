import { useLayoutEffect, useRef, useState } from "react";

import { clipAtWord } from "./clip-text";

/**
 * A clamped text cut at a word instead of inside one (CSS line-clamp puts its ellipsis wherever the line ends). The
 * caller's box carries the clamp (its lines and `overflow: hidden`); this measures a hidden copy of it with the same
 * classes and width and returns the longest run of whole words that fits, with "…", or null when the whole text fits.
 * The caller draws the clipped text `aria-hidden` and keeps the whole text in the page for screen readers; the CSS
 * clamp only backs it up. Measured while `active` (an opened text cannot tell whether it overflows, so `clipped` keeps
 * its last value while the text is open), again when the window or the box changes width and when a web font arrives.
 */
export function useWordClip<T extends HTMLElement>(
  text: string,
  active: boolean,
) {
  const ref = useRef<T>(null);
  const [clipped, setClipped] = useState<string | null>(null);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || !active) return;
    function measure() {
      if (!el) return;
      // A hidden copy beside the box, same classes and width, so the real text is untouched while measuring.
      const probe = el.cloneNode(false) as T;
      probe.style.visibility = "hidden";
      probe.style.position = "absolute";
      probe.style.width = `${el.getBoundingClientRect().width}px`;
      el.after(probe);
      const fits = (candidate: string) => {
        probe.textContent = candidate;
        return probe.scrollHeight <= probe.clientHeight + 1;
      };
      const result = clipAtWord(text, fits);
      probe.remove();
      setClipped(result === text ? null : result);
    }
    measure();
    window.addEventListener("resize", measure);
    // A web font that arrives after the first measure changes every line's width.
    const fonts = typeof document !== "undefined" ? document.fonts : undefined;
    fonts?.addEventListener?.("loadingdone", measure);
    // The box can change without the window: its width beside a list, its line height when the host's text size
    // arrives. A new cut keeps the box at the clamp's lines, so measuring again settles.
    let size = el.getBoundingClientRect();
    const observer =
      typeof ResizeObserver === "undefined"
        ? null
        : new ResizeObserver(() => {
            const now = el.getBoundingClientRect();
            if (
              Math.abs(now.width - size.width) < 0.5 &&
              Math.abs(now.height - size.height) < 0.5
            )
              return;
            size = now;
            measure();
          });
    observer?.observe(el);
    return () => {
      window.removeEventListener("resize", measure);
      fonts?.removeEventListener?.("loadingdone", measure);
      observer?.disconnect();
    };
  }, [text, active]);
  return { ref, clipped };
}
