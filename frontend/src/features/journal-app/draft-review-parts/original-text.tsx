import { useState } from "react";
import type { JournalLabels } from "../labels";
import type { JournalSource } from "../transport";

/** The unchanged original behind a toggle; only shown when the source carries its text. */
export function OriginalText({
  source,
  labels: t,
}: {
  source: JournalSource | undefined;
  labels: JournalLabels;
}) {
  const [showOriginal, setShowOriginal] = useState(false);
  return (
    <>
      <h3 className="journal-disclosure-head">{t.originalUnchanged}</h3>
      <p className="journal-draft-action">
        <button
          type="button"
          className="sk-btn--quiet journal-toggle"
          aria-expanded={showOriginal}
          onClick={() => setShowOriginal((on) => !on)}
        >
          {showOriginal ? t.hideOriginal : t.showOriginal}
        </button>
      </p>
      {showOriginal &&
        (typeof source?.raw_text === "string" ? (
          <pre className="journal-original">{source.raw_text}</pre>
        ) : (
          <p className="journal-muted">{t.originalNote}</p>
        ))}
    </>
  );
}
