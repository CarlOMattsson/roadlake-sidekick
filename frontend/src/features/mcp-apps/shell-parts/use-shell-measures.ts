import { useLayoutEffect, useRef, useState } from "react";

/**
 * What the shell measures about its strip: the bar's height, published as `--sk-bar-h` (what a room keeps sticky
 * rests below it), and whether the room tabs fit one row (`narrow`: the room picker takes their place).
 */
export function useShellMeasures(full: boolean, stripVisible: boolean) {
  // The strip's four labels do not fit one row (large text): the room picker "Arbete ⌄" takes their place.
  const [narrow, setNarrow] = useState(false);
  const tabsEl = useRef<HTMLDivElement | null>(null);
  const shellEl = useRef<HTMLDivElement | null>(null);
  const barEl = useRef<HTMLDivElement | null>(null);

  // The strip is sticky at the top. What a room keeps sticky (the board's column switch, the agenda's
  // group headings) must rest below it, not under or over it: the shell tells them how tall the strip is.
  useLayoutEffect(() => {
    const shell = shellEl.current;
    const bar = barEl.current;
    if (!shell) return undefined;
    const measure = () =>
      shell.style.setProperty("--sk-bar-h", `${bar ? bar.offsetHeight : 0}px`);
    measure();
    if (!bar || typeof ResizeObserver === "undefined") return undefined;
    const observer = new ResizeObserver(measure);
    observer.observe(bar);
    return () => observer.disconnect();
  }, [full, stripVisible]);

  // Whether the four rooms fit: measured, never by breakpoint. The tabs keep their width while hidden, so they go on
  // measuring whether they fit again.
  useLayoutEffect(() => {
    const row = tabsEl.current;
    if (!row) return undefined;
    const fit = () => setNarrow(row.scrollWidth > row.clientWidth + 1);
    fit();
    if (typeof ResizeObserver === "undefined") return undefined;
    const sizes = new ResizeObserver(fit);
    sizes.observe(row);
    for (const tab of Array.from(row.children)) sizes.observe(tab);
    return () => sizes.disconnect();
  }, [full, stripVisible]);

  return { narrow, tabsEl, shellEl, barEl };
}
