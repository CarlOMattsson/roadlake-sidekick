import { useEffect, useRef, useState } from "react";
import { formatShortDateWithYear, formatTime } from "./dates";
import { labelFor } from "./labels";
import { isForbidden } from "./transport";
import type { JournalSource } from "./transport";
import { ownerToday } from "../mcp-apps/app-timezone";
import { ErrorNotice } from "../mcp-apps/ui/states";
import type { FrameProps, LoadPhase } from "./frame-props";

/** A language code as its name in the owner's language: "sv" reads "svenska" in Swedish, "Swedish" in English. */
function languageName(code: string, locale: string): string {
  try {
    return new Intl.DisplayNames(locale, { type: "language" }).of(code) ?? code;
  } catch {
    // A code Intl cannot read is shown as it came.
    return code;
  }
}

export function SourceFrame({
  id,
  transport,
  labels: t,
  moves,
  onBack,
}: FrameProps & { id: string; onBack?: () => void }) {
  const [phase, setPhase] = useState<LoadPhase>("loading");
  const [source, setSource] = useState<JournalSource>();
  const [cause, setCause] = useState<unknown>();
  const [attempt, setAttempt] = useState(0);
  const heading = useRef<HTMLHeadingElement>(null);
  useEffect(() => {
    if (moves > 0) heading.current?.focus();
  }, [moves]);
  useEffect(() => {
    // Only reached through the link to the original, which a transport without getSource does not draw.
    if (!transport.getSource) return undefined;
    let current = true;
    transport
      .getSource(id)
      .then(({ source: loaded }) => {
        if (!current) return;
        setSource(loaded);
        setPhase("ready");
      })
      .catch((error: unknown) => {
        if (!current) return;
        setCause(error);
        setPhase(isForbidden(error) ? "forbidden" : "error");
      });
    return () => {
      current = false;
    };
  }, [transport, id, attempt]);

  return (
    <article>
      <h2 ref={heading} tabIndex={-1}>
        {t.originalHeading}
      </h2>
      {phase === "loading" && <p role="status">{t.loading}</p>}
      {phase === "forbidden" && <p>{t.forbidden}</p>}
      {phase === "error" && (
        <ErrorNotice
          locale={t.dateLocale}
          cause={cause}
          onRetry={() => setAttempt((n) => n + 1)}
        />
      )}
      {phase === "ready" && source && (
        <>
          <p className="journal-muted">{t.originalNote}</p>
          <p>
            {labelFor(t.sourceType, source.source_type)} ·{" "}
            {formatShortDateWithYear(
              source.journal_date,
              t.dateLocale,
              ownerToday(),
            )}
          </p>
          {source.source_recorded_at && (
            <p>
              {t.sourceRecorded}:{" "}
              <time dateTime={source.source_recorded_at}>
                {formatTime(source.source_recorded_at, t.dateLocale)}
              </time>
            </p>
          )}
          {source.language && (
            <p>
              {t.language}: {languageName(source.language, t.dateLocale)}
            </p>
          )}
          {typeof source.raw_text === "string" && source.raw_text.length > 0 ? (
            <pre className="journal-original">{source.raw_text}</pre>
          ) : (
            <p className="journal-muted">{t.originalEmpty}</p>
          )}
        </>
      )}
      {/* With the shell's navigation, its Back returns to the entry, so no "show summary" line here. */}
      {onBack && (
        <p>
          <button
            type="button"
            className="sk-btn--quiet journal-toggle"
            onClick={onBack}
          >
            {t.showSummary}
          </button>
        </p>
      )}
    </article>
  );
}
