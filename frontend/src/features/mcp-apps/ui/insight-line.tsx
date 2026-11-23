import { useState } from "react";

import "./family.css";
import { ChevronRightIcon } from "./icons";
import { insightLabelsFor } from "./insight-labels";
import "./insight-line.css";
import "./tokens.css";
import { useWordClip } from "./use-word-clip";

export type InsightDensity = "list" | "inline" | "detail";

/**
 * One sentence that says what Sidekick noticed ("Du sov dåligt, så den tunga uppgiften flyttades till imorgon."), in
 * the body type, without a heading, as the first block of a view. The server writes it in the app's language; a view
 * without a sentence draws nothing, so an empty `text` renders null.
 *
 * - `list` (the default, a full-screen list): at most two lines, cut at a word with an ellipsis. `onMore` adds
 *   "Visa mer ›" under it, which opens the view that says more (where the same sentence stands whole, with its
 *   graphs). Without `onMore` a sentence the two lines cut gets "Visa mer" in place instead (no ›: it opens nothing),
 *   so it can always be read whole.
 * - `inline` (an inline card): the same two lines and no button; the card's own link row leads on.
 * - `detail`: the sentence in full and no button.
 *
 * A screen reader always reads the whole sentence; the cut one is drawn `aria-hidden`.
 */
export function InsightLine({
  text,
  locale,
  density = "list",
  onMore,
  className,
}: {
  text: string;
  locale: string;
  density?: InsightDensity;
  onMore?: () => void;
  className?: string;
}) {
  const t = insightLabelsFor(locale);
  const [open, setOpen] = useState(false);
  const clamped = density !== "detail" && !open;
  const { ref, clipped } = useWordClip<HTMLParagraphElement>(text, clamped);
  if (!text.trim()) return null;
  const list = density === "list";
  const inPlace = list && !onMore && clipped !== null;
  return (
    <div
      className={className ? `sk-insight ${className}` : "sk-insight"}
      data-density={density}
    >
      <p
        ref={ref}
        className="sk-insight__text"
        data-clamped={clamped ? "" : undefined}
      >
        {clamped && clipped !== null ? (
          <>
            <span aria-hidden="true">{clipped}</span>
            <span className="sk-insight__whole">{text}</span>
          </>
        ) : (
          text
        )}
      </p>
      {list && onMore ? (
        <button
          type="button"
          className="sk-btn sk-btn--quiet sk-btn--compact sk-insight__more"
          onClick={onMore}
        >
          {t.more}
          <ChevronRightIcon />
        </button>
      ) : inPlace ? (
        <button
          type="button"
          className="sk-btn sk-btn--quiet sk-btn--compact sk-insight__more"
          aria-expanded={open}
          onClick={() => setOpen((value) => !value)}
        >
          {open ? t.less : t.more}
        </button>
      ) : null}
    </div>
  );
}
