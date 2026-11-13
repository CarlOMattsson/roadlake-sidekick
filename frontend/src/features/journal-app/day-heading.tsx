import { useLayoutEffect, useState } from "react";
import type { RefObject } from "react";

/**
 * The day view's heading on its title row, beside + and ⋯. When the long form does not fit one line of the row
 * ("Wednesday 4 November" at 375 px), it shows the short weekday ("Wed 4 November") and keeps the long form as
 * its name for a screen reader. The text is measured in the heading's own font, again when the row's width
 * changes and once the fonts have loaded. Without layout (no width) it keeps the long form.
 */
export function DayHeading({
  ref,
  long,
  short,
}: {
  ref: RefObject<HTMLHeadingElement | null>;
  long: string;
  short: string;
}) {
  const [fits, setFits] = useState(true);
  useLayoutEffect(() => {
    const heading = ref.current;
    if (!heading || long === short) return;
    let live = true;
    let pen: CanvasRenderingContext2D | null | undefined;
    const check = () => {
      const room = heading.clientWidth;
      if (!live || room === 0) return;
      pen ??= document.createElement("canvas").getContext("2d");
      if (!pen) return;
      const style = getComputedStyle(heading);
      pen.font = `${style.fontStyle} ${style.fontWeight} ${style.fontSize} ${style.fontFamily}`;
      setFits(pen.measureText(long).width <= room);
    };
    check();
    const observer =
      typeof ResizeObserver === "undefined"
        ? undefined
        : new ResizeObserver(check);
    observer?.observe(heading);
    void document.fonts?.ready.then(check);
    return () => {
      live = false;
      observer?.disconnect();
    };
  }, [ref, long, short]);
  const shortened = !fits && long !== short;
  return (
    <h2 ref={ref} tabIndex={-1} aria-label={shortened ? long : undefined}>
      {shortened ? short : long}
    </h2>
  );
}
