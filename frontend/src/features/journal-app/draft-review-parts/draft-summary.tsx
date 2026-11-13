import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import type { JournalLabels } from "../labels";

/**
 * The summary. Inline it is clamped to three lines, with "Läs mer" when the text is longer; fullscreen has no
 * clamp, so it shows the whole text and no toggle. An expanded text cannot tell whether it overflows, so the
 * check runs only while it is clamped; the toggle then stays up to collapse it again. `after` comes under the
 * text; inline it shares the row with "Läs mer" (journal.css), so it costs the card no row of its own.
 */
export function DraftSummary({
  text,
  after,
  labels: t,
}: {
  text: string;
  after?: ReactNode;
  labels: JournalLabels;
}) {
  const ref = useRef<HTMLParagraphElement>(null);
  const [expanded, setExpanded] = useState(false);
  const [long, setLong] = useState(false);
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    function measure() {
      if (el) setLong(el.scrollHeight > el.clientHeight + 1);
    }
    measure();
    window.addEventListener("resize", measure);
    return () => window.removeEventListener("resize", measure);
  }, [text, expanded]);
  return (
    <>
      <p
        ref={ref}
        className={
          expanded
            ? "journal-summary"
            : "journal-summary journal-summary-clamped"
        }
      >
        {text}
      </p>
      {(long || after) && (
        <div className="journal-summary-row">
          {long && (
            <p>
              <button
                type="button"
                className="sk-btn--quiet journal-toggle journal-summary-more"
                aria-expanded={expanded}
                onClick={() => setExpanded((on) => !on)}
              >
                {expanded ? t.showLess : t.readMore}
              </button>
            </p>
          )}
          {after}
        </div>
      )}
    </>
  );
}
