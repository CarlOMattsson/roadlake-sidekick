import { useLayoutEffect, useRef, useState } from "react";
import type { ReactNode } from "react";
import { clipAtWord } from "../../mcp-apps/ui/clip-text";
import type { JournalLabels } from "../labels";

/**
 * The summary. Inline it is clamped to three lines, with `readMore` when the text is longer; fullscreen has no
 * clamp, so it shows the whole text and no toggle. The cut is made here at a word boundary (CSS would cut inside a
 * word) and the CSS clamp only backs it up; the whole text stays in the page for screen readers. An expanded text
 * cannot tell whether it overflows, so the check runs only while it is clamped; the toggle then stays up to
 * collapse it again. `after` comes under the
 * text; inline it shares the row with `readMore` (journal.css), so it costs the card no row of its own.
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
  const [clipped, setClipped] = useState<string | null>(null);
  const long = clipped !== null;
  useLayoutEffect(() => {
    const el = ref.current;
    if (!el || expanded) return;
    function measure() {
      if (!el) return;
      // A hidden copy beside the paragraph, same classes and width, so the real text is untouched while measuring.
      const probe = el.cloneNode(false) as HTMLParagraphElement;
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
        {clipped !== null && !expanded ? (
          <>
            <span aria-hidden="true">{clipped}</span>
            <span className="journal-visually-hidden">{text}</span>
          </>
        ) : (
          text
        )}
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
