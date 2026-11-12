import { useEffect, useState } from "react";

/** 17.25rem is a 412 px frame at 150 % text: the same line the CSS draws with `@container sk-frame (max-width: 17.25rem)`. */
function readLarge(): boolean {
  if (typeof window === "undefined") return false;
  const rem = parseFloat(getComputedStyle(document.documentElement).fontSize);
  return window.innerWidth / (rem || 16) <= 17.25;
}

/**
 * True at large text (≥ 150 % on a phone): the row menu folds its groups there, so it fits between the
 * host's chrome and its reply field. Read on mount, on resize, and when the text size itself changes: a
 * change of the root font size fires no `resize`, so a probe one em wide per root rem is watched for its width. The
 * probe is `width: 10rem` and takes no space; the observer reports when the rem, and so the text size, moves.
 */
export function useLargeText(): boolean {
  const [large, setLarge] = useState(readLarge);
  useEffect(() => {
    const read = () => setLarge(readLarge());
    // A change after the first render and before this effect is read at once.
    read();
    window.addEventListener("resize", read);
    let probe: HTMLElement | undefined;
    let sizes: ResizeObserver | undefined;
    if (typeof ResizeObserver !== "undefined") {
      probe = document.createElement("div");
      probe.setAttribute("aria-hidden", "true");
      probe.style.cssText =
        "position:fixed;inset-block-start:0;inset-inline-start:0;width:10rem;height:0;visibility:hidden;pointer-events:none;";
      document.body.append(probe);
      sizes = new ResizeObserver(read);
      sizes.observe(probe);
    }
    return () => {
      window.removeEventListener("resize", read);
      sizes?.disconnect();
      probe?.remove();
    };
  }, []);
  return large;
}
