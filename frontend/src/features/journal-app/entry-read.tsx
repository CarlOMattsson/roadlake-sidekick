import { useEffect, useId, useState, type ReactNode } from "react";
import { Fold } from "../mcp-apps/ui/fold";
import { originalLine, summaryRest } from "./entry-card";
import { labelFor, type JournalLabels } from "./labels";
import type {
  JournalEntry,
  JournalSource,
  JournalTransport,
} from "./transport";
import "./entry.css";
import "./entry-read.css";

/**
 * What is known of the entry's original text. `none`: the transport cannot read originals (the phone), so nothing was
 * asked. `failed` covers a refusal and an error alike: the entry then reads as it did before the original was asked for.
 */
export type SourceState =
  | { phase: "none" | "loading" | "failed" }
  | { phase: "ready"; source: JournalSource };

/**
 * Reads the entry's original text once the entry is shown, and again when the entry changes (an added text grows the
 * original, never the summary Claude wrote). The owner opened their own entry, so the app asks for the content
 * (`getSource`). While the entry's version changes the source that was read stays, so the text does not blink.
 */
export function useEntrySource(
  transport: JournalTransport,
  entry: JournalEntry | undefined,
): SourceState {
  const sourceId = entry?.source_id;
  const version = entry?.version;
  const read = transport.getSource;
  const [state, setState] = useState<{ id: string; value: SourceState }>();
  useEffect(() => {
    if (!sourceId || !read) return undefined;
    let current = true;
    // Starting from a resolved promise also turns a transport that throws into a failed read, and an answer without a
    // source is one too.
    void Promise.resolve()
      .then(() => read(sourceId))
      .then(({ source }): SourceState => ({ phase: "ready", source }))
      .catch((): SourceState => ({ phase: "failed" }))
      .then((value) => {
        if (current) setState({ id: sourceId, value });
      });
    return () => {
      current = false;
    };
  }, [read, sourceId, version]);
  if (!sourceId || !read) return { phase: "none" };
  return state?.id === sourceId ? state.value : { phase: "loading" };
}

/** What the reading view shows as the entry's text, and what it says about the original. */
export type EntryText = {
  /** The owner's own text, or the summary when there is no other text; undefined while the original is read. */
  main: string | undefined;
  /** True until the original has been asked for and answered. */
  waiting: boolean;
  /** Claude's summary, kept apart under the text; undefined when it is the text itself or says only the title. */
  summary: string | undefined;
  /** "Show original" is offered: the text is a transcription, or the original is not what stands above it. */
  original: boolean;
};

/** The sources that are written by hand; every other source is a transcript of something said or recorded. */
function typedByHand(source: JournalSource): boolean {
  return source.source_type === "manual_text";
}

/**
 * Which text is the entry's text. The owner's words come first: a summary that holds them (`summary_by` "you", written
 * or corrected by hand) or else the original text of the source, which holds them as typed, dictated or transcribed.
 * With neither, Claude's summary is the text, as it was before. "Show original" is for the text that is not simply the
 * original: a transcription, or words corrected since they were saved. Under a hand-written text it would only say that
 * the text is what it is.
 */
export function entryTextOf(
  entry: Pick<JournalEntry, "title" | "summary" | "summary_by">,
  state: SourceState,
): EntryText {
  const summary = entry.summary?.trim() ? entry.summary : undefined;
  const raw =
    state.phase === "ready" && state.source.raw_text?.trim()
      ? state.source.raw_text
      : undefined;
  if (summary && entry.summary_by === "you") {
    const differs = raw !== undefined && raw.trim() !== summary.trim();
    return {
      main: summary,
      waiting: false,
      summary: undefined,
      original: state.phase === "failed" || differs,
    };
  }
  if (state.phase === "loading")
    return {
      main: undefined,
      waiting: true,
      summary: undefined,
      original: false,
    };
  const rest = summaryRest(entry.title, entry.summary);
  if (state.phase === "ready" && raw !== undefined)
    return {
      main: raw,
      waiting: false,
      // A summary that is the very text (an older server does not say who wrote it) is not said twice.
      summary: rest?.trim() === raw.trim() ? undefined : rest,
      original: !typedByHand(state.source),
    };
  return {
    main: rest,
    waiting: false,
    summary: undefined,
    original: state.phase === "failed",
  };
}

/**
 * The entry as it is read: the owner's text first, in the reading type and width, with the paragraphs as they were
 * written; the line about the original under it when it applies; then one quiet fold ("Claude's summary") that holds
 * Claude's summary and the key points, and last what the entry is linked to, in sight. The links are the way on to a
 * contact, a project or a task (one tap, no model turn), not Claude's prose, so they are not folded away. A fold with
 * nothing in it is not drawn.
 */
export function EntryReadBody({
  entry,
  state,
  labels: t,
  onShowOriginal,
  linked,
}: {
  entry: JournalEntry;
  state: SourceState;
  labels: JournalLabels;
  /** Opens the original text; absent when the transport cannot read it. */
  onShowOriginal?: () => void;
  /** What the entry is linked to (links, tasks), drawn under the fold; null when it is linked to nothing. */
  linked: ReactNode;
}) {
  const text = entryTextOf(entry, state);
  const [open, setOpen] = useState(false);
  const regionId = useId();
  const hasPoints = entry.key_points.length > 0;
  // The fold is named by the first thing in it.
  const foldTitle = text.summary ? t.claudeSummary : t.keyPoints;
  return (
    <>
      {text.waiting && (
        <p className="journal-muted" role="status">
          {t.loading}
        </p>
      )}
      {text.main && <div className="journal-entry-text">{text.main}</div>}
      {text.original && (
        <div className="journal-original-row">
          <p className="journal-muted">
            {originalLine(entry.summary, t, entry.summary_by)}
          </p>
          {onShowOriginal && (
            <button
              type="button"
              className="sk-btn--quiet journal-toggle"
              onClick={onShowOriginal}
            >
              {t.showOriginal}
            </button>
          )}
        </div>
      )}
      {/* Not drawn while the original is read: the fold is named by what is first in it, and that is not known yet. */}
      {!text.waiting && (text.summary || hasPoints) && (
        <section className="journal-entry-more">
          <Fold
            className="journal-entry-fold"
            text={foldTitle}
            open={open}
            onToggle={() => setOpen((value) => !value)}
            controls={regionId}
          />
          {open && (
            <div id={regionId} className="journal-entry-more__body">
              {text.summary && (
                <p className="journal-summary">{text.summary}</p>
              )}
              {hasPoints && (
                <>
                  <h3>{t.keyPoints}</h3>
                  <ul className="journal-list">
                    {entry.key_points.map((point, index) => (
                      <li key={index}>
                        <p>
                          {labelFor(t.keyPointKind, point.kind)}: {point.text}
                        </p>
                      </li>
                    ))}
                  </ul>
                </>
              )}
            </div>
          )}
        </section>
      )}
      {linked}
    </>
  );
}
