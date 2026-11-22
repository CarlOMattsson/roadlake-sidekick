import { useLayoutEffect, useRef, useState } from "react";

/** The frame width (root rem) from which the shell's head is one row: the desktop layer (desktop spec §1, "bred"). */
export const WIDE_FROM_REM = 64;

/**
 * Whether the app's frame (`.sk-frame`, the container every width rule reads) is at least 64 rem wide, in the root's
 * rem, so large text falls back to the narrower layout as the container queries do.
 */
function isWide(shell: HTMLElement): boolean {
  const frame = shell.closest<HTMLElement>(".sk-frame") ?? shell;
  const rem =
    parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  return frame.clientWidth >= WIDE_FROM_REM * rem;
}

/**
 * What the shell measures about its strip: the bar's height, published as `--sk-bar-h` (what a room keeps sticky
 * rests below it), whether the room tabs fit one row (`narrow`: the room picker takes their place) and whether the
 * frame is wide (`wide`: the room's head moves into the bar's row).
 */
export function useShellMeasures(full: boolean, stripVisible: boolean) {
  // The strip's four labels do not fit one row (large text): the room picker takes their place.
  const [narrow, setNarrow] = useState(false);
  const [wide, setWide] = useState(false);
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

  // The frame's width, read before paint and on every resize of the frame (a host that resizes the iframe, text zoom).
  useLayoutEffect(() => {
    const shell = shellEl.current;
    if (!shell || !full) {
      setWide(false);
      return undefined;
    }
    const read = () => setWide(isWide(shell));
    read();
    window.addEventListener("resize", read);
    const frame = shell.closest<HTMLElement>(".sk-frame");
    const sizes =
      frame && typeof ResizeObserver !== "undefined"
        ? new ResizeObserver(read)
        : undefined;
    if (frame) sizes?.observe(frame);
    return () => {
      window.removeEventListener("resize", read);
      sizes?.disconnect();
    };
  }, [full]);

  return { narrow, wide, tabsEl, shellEl, barEl };
}
