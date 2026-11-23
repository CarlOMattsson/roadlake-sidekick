import { useLayoutEffect, useRef, useState, type RefObject } from "react";

/** The frame width (root rem) from which the shell's head is one row: the desktop layer (desktop spec §1, "bred"). */
export const WIDE_FROM_REM = 64;
/** The widest frame (root rem) that is a phone's: where the room strip's glyphs stand for the names (sidekick-shell.css). */
export const PHONE_TO_REM = 32;
/** A frame this narrow (root rem) is large text on a phone, 412 px at 150 %: the names stand alone again. */
export const LARGE_TEXT_TO_REM = 17.25;

/** How wide the app's frame is, as the classes the shell acts on. */
type FrameWidth = {
  /** At least 64 rem: the room's head moves into the bar's row. */
  wide: boolean;
  /** A phone's frame at an ordinary text size: wider than 17.25 rem and at most 32 rem. */
  phone: boolean;
};

/**
 * The class of a frame's width, in the root's rem, so large text falls back to the narrower layout as the container
 * queries do. `frame` is the app's frame (`.sk-frame`, the container every width rule reads) or, before there is one
 * to read, the document it spans.
 */
function widthClass(frame: HTMLElement): FrameWidth {
  const rem =
    parseFloat(getComputedStyle(document.documentElement).fontSize) || 16;
  const width = frame.clientWidth / rem;
  return {
    wide: width >= WIDE_FROM_REM,
    phone: width > LARGE_TEXT_TO_REM && width <= PHONE_TO_REM,
  };
}

/**
 * The frame's width class, read before paint and on every resize of the frame (a host that resizes the iframe, text
 * zoom), and the ref of the shell's root it is read from. Neither class holds outside a full view.
 *
 * Whether the frame is a phone's is first read from the document, which the frame spans in a host's iframe: the
 * strip's cells are then drawn as they will stay in the very render that makes the view full, and nothing is drawn
 * twice.
 */
export function useFrame(full: boolean): FrameWidth & {
  shellEl: RefObject<HTMLDivElement | null>;
} {
  const [wide, setWide] = useState(false);
  const [phoneFrame, setPhoneFrame] = useState(
    () => widthClass(document.documentElement).phone,
  );
  const shellEl = useRef<HTMLDivElement | null>(null);

  useLayoutEffect(() => {
    const shell = shellEl.current;
    if (!shell || !full) {
      setWide(false);
      return undefined;
    }
    const frame = shell.closest<HTMLElement>(".sk-frame");
    const read = () => {
      const width = widthClass(frame ?? shell);
      setWide(width.wide);
      setPhoneFrame(width.phone);
    };
    read();
    window.addEventListener("resize", read);
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

  return { wide, phone: full && phoneFrame, shellEl };
}

/**
 * What the shell measures about its strip: the bar's height, published as `--sk-bar-h` (what a room keeps sticky
 * rests below it), and whether the room tabs fit one row (`narrow`: the room picker takes their place).
 */
export function useBarMeasures(
  full: boolean,
  stripVisible: boolean,
  shellEl: RefObject<HTMLDivElement | null>,
) {
  // The strip's four labels do not fit one row (large text): the room picker takes their place.
  const [narrow, setNarrow] = useState(false);
  const tabsEl = useRef<HTMLDivElement | null>(null);
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
  }, [full, stripVisible, shellEl]);

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

  return { narrow, tabsEl, barEl };
}
