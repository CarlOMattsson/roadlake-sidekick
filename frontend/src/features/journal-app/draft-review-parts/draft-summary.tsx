import { useState } from "react";
import type { ReactNode } from "react";
import { useWordClip } from "../../mcp-apps/ui/use-word-clip";
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
  const [expanded, setExpanded] = useState(false);
  const { ref, clipped } = useWordClip<HTMLParagraphElement>(text, !expanded);
  const long = clipped !== null;
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
