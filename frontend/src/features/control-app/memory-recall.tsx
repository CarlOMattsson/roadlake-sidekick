import { useEffect, useId, useRef, useState } from "react";
import { onEnterKey, preventSubmit } from "../mcp-apps/ui/enter-key";
import { ErrorNotice } from "../mcp-apps/ui/states";
import { actionName, kindName, type ControlLabels } from "./labels";
import { ControlRow, NoticeLine, type Notice } from "./control-parts";
import { dateText } from "./when";
import {
  DOMAIN_KIND,
  domainOfKind,
  writeFailure,
  type ControlTransport,
  type MemoryKind,
  type RecallResult,
  type RecalledFact,
} from "./transport";

/** The two memory tools the view offers; the view draws nothing of this when the host lacks one. */
export type RecallTools = Required<Pick<ControlTransport, "recall" | "forget">>;

/** What the transport holds of the two tools, or undefined when the host offers only one or none. */
export function recallTools(
  transport: ControlTransport,
): RecallTools | undefined {
  const { recall, forget } = transport;
  return recall && forget ? { recall, forget } : undefined;
}

/** The record a fact came from, as one key. The id never reaches the screen. */
const sourceKey = (fact: RecalledFact) =>
  `${fact.source.kind}:${fact.source.id}`;

/**
 * The facts of a recall that can be drawn. A fact of the wrong shape (no text, no source, a kind the memory does not
 * know) is dropped quietly, so one bad fact does not take the whole list down.
 */
export function drawableFacts(result: RecallResult): RecalledFact[] {
  const facts: unknown = result.facts;
  if (!Array.isArray(facts)) return [];
  return facts.filter((fact): fact is RecalledFact => {
    if (typeof fact !== "object" || fact === null) return false;
    const { text, source } = fact as Partial<RecalledFact>;
    return (
      typeof text === "string" &&
      typeof source === "object" &&
      source !== null &&
      typeof source.id === "string" &&
      (Object.values(DOMAIN_KIND) as unknown[]).includes(source.kind) &&
      (source.title == null || typeof source.title === "string")
    );
  });
}

type Load =
  | { state: "loading" }
  | { state: "failed"; cause: unknown }
  | { state: "done"; result: RecallResult };

/**
 * One source's "Show what Sidekick remembers": a button that folds out a small read only sample, answered by
 * recall_memory narrowed to the source's kind. Nothing is read until the owner opens it.
 */
export function SourceRecall({
  kind,
  name,
  tools,
  labels,
  onForgotten,
  onModelContext,
}: {
  kind: MemoryKind;
  /** The source's name, for the button's spoken label. */
  name: string;
  tools: RecallTools;
  labels: ControlLabels;
  onForgotten?: () => void;
  onModelContext?: (summary: string) => void;
}) {
  const [open, setOpen] = useState(false);
  const panelId = useId();
  return (
    <>
      <button
        type="button"
        className="sk-btn--secondary sk-btn--compact control-recall-toggle"
        aria-expanded={open}
        aria-controls={panelId}
        aria-label={
          open ? labels.recallHideLabel(name) : labels.recallShowLabel(name)
        }
        onClick={() => setOpen(!open)}
      >
        {open ? labels.recallHide : labels.recallShow}
      </button>
      <div id={panelId}>
        {open ? (
          <RecallResults
            request={{ query: labels.recallProbe, kind }}
            sample
            tools={tools}
            labels={labels}
            onForgotten={onForgotten}
            onModelContext={onModelContext}
          />
        ) : null}
      </div>
    </>
  );
}

/**
 * The facts one recall returned, each with "Forget the <record>". Forgetting is destructive for the memory (not for the
 * record), so it asks in the row first: a red frame, what happens, then the red button and Cancel. It excludes the
 * whole source record, so every fact from it leaves the list. States: reading, empty, the memory being paused or off,
 * and a failure with Try again. Mount it afresh (a new `key`) for a new request.
 */
export function RecallResults({
  request,
  sample = false,
  tools,
  labels,
  onForgotten,
  onModelContext,
}: {
  request: { query: string; kind?: MemoryKind };
  /** A broad sample of one source, not an answer to a question: the list says it is not everything. */
  sample?: boolean;
  tools: RecallTools;
  labels: ControlLabels;
  /** Called after a record was kept out of memory, so the view can read its counts again. */
  onForgotten?: () => void;
  onModelContext?: (summary: string) => void;
}) {
  const [load, setLoad] = useState<Load>({ state: "loading" });
  const [attempt, setAttempt] = useState(0);
  // Source records kept out of memory in this list: their facts are hidden at once.
  const [gone, setGone] = useState<string[]>([]);
  const [confirming, setConfirming] = useState<number | null>(null);
  const [busy, setBusy] = useState(false);
  const [notice, setNotice] = useState<Notice | undefined>();
  const confirmRef = useRef<HTMLDivElement>(null);
  const noticeRef = useRef<HTMLDivElement>(null);
  const forgetButtons = useRef(new Map<number, HTMLButtonElement>());

  const { query, kind } = request;
  const { recall } = tools;
  useEffect(() => {
    let current = true;
    recall({ query, ...(kind === undefined ? {} : { kind }) }).then(
      (result) => {
        if (current) setLoad({ state: "done", result });
      },
      (cause: unknown) => {
        if (current) setLoad({ state: "failed", cause });
      },
    );
    return () => {
      current = false;
    };
  }, [recall, query, kind, attempt]);

  // Move focus to the question, so a screen reader reads it and the buttons are next in order.
  useEffect(() => {
    if (confirming !== null) confirmRef.current?.focus();
  }, [confirming]);

  function retry() {
    setLoad({ state: "loading" });
    setAttempt((n) => n + 1);
  }

  if (load.state === "loading")
    return (
      <p className="control-recall-line" role="status">
        {labels.recallLooking}
      </p>
    );
  if (load.state === "failed") return failedRecall(load.cause, labels, retry);

  const { status } = load.result;
  if (status === "unavailable")
    return (
      <ErrorNotice
        locale={labels.locale}
        message={labels.recallUnavailableHeading}
        onRetry={retry}
        placement="row"
      />
    );
  if (status === "paused" || status === "disabled")
    return (
      <p className="control-recall-line">
        {status === "paused" ? labels.recallPaused : labels.recallOff}
      </p>
    );

  const facts = drawableFacts(load.result).filter(
    (fact) => !gone.includes(sourceKey(fact)),
  );

  async function forget(fact: RecalledFact) {
    if (busy) return;
    setBusy(true);
    setNotice(undefined);
    try {
      await tools.forget(fact);
      setConfirming(null);
      setGone((current) => [...current, sourceKey(fact)]);
      onModelContext?.(labels.modelNote.forgotten);
      setNotice({
        tone: "ok",
        text: labels.forgotten(
          domainOfKind(fact.source.kind),
          fact.source.title,
        ),
      });
      onForgotten?.();
      // The row and its button are gone: the status line is where focus rests.
      queueMicrotask(() => noticeRef.current?.focus());
    } catch (error) {
      setConfirming(null);
      setNotice({
        tone: "error",
        text:
          writeFailure(error) === "forbidden"
            ? labels.forgetForbidden
            : labels.forgetFailed,
        retry:
          writeFailure(error) === "forbidden"
            ? undefined
            : () => void forget(fact),
      });
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="control-recall">
      {notice ? (
        <div ref={noticeRef} tabIndex={-1}>
          <NoticeLine notice={notice} locale={labels.locale} />
        </div>
      ) : null}
      {facts.length === 0 ? (
        <p className="control-recall-line">
          {sample ? labels.recallEmpty : labels.recallNothing}
        </p>
      ) : (
        <>
          {sample ? (
            <p className="control-recall-line">{labels.recallSample}</p>
          ) : null}
          <ul
            className="control-list control-list-wrap"
            aria-label={labels.resultsLabel}
          >
            {facts.map((fact, index) => {
              const title = fact.source.title;
              const domain = domainOfKind(fact.source.kind);
              // Where the fact comes from: the kind, the record's title, the day it concerns and a mark if archived.
              const secondary = [
                kindName(labels, fact.source.kind),
                title,
                dateText(
                  fact.source.date ?? fact.occurred,
                  new Date(),
                  labels.locale,
                ),
                fact.source.archived
                  ? actionName(labels, "archived", fact.source.kind)
                  : "",
              ]
                .filter(Boolean)
                .join(" · ");
              return (
                <ControlRow
                  key={`${sourceKey(fact)}:${index}`}
                  primary={fact.text}
                  secondary={secondary}
                  action={
                    <button
                      type="button"
                      className="sk-btn--secondary sk-btn--compact control-row-btn"
                      aria-label={labels.forgetLabel(domain, title)}
                      disabled={busy || confirming !== null}
                      ref={(node) => {
                        if (node) forgetButtons.current.set(index, node);
                        else forgetButtons.current.delete(index);
                      }}
                      onClick={() => setConfirming(index)}
                    >
                      {labels.forget(domain)}
                    </button>
                  }
                  below={
                    confirming === index ? (
                      <div
                        ref={confirmRef}
                        tabIndex={-1}
                        role="group"
                        aria-label={labels.forgetTitle(domain, title)}
                        className="control-confirm"
                      >
                        <p className="control-confirm-title">
                          {labels.forgetTitle(domain, title)}
                        </p>
                        <p>{labels.forgetBody(domain)}</p>
                        <div className="control-confirm-actions">
                          {/* Cancel comes first in the DOM, so Tab reaches the safe button before the red one. */}
                          <button
                            type="button"
                            className="sk-btn--quiet"
                            disabled={busy}
                            onClick={() => {
                              setConfirming(null);
                              queueMicrotask(() =>
                                forgetButtons.current.get(index)?.focus(),
                              );
                            }}
                          >
                            {labels.forgetNo}
                          </button>
                          <button
                            type="button"
                            className="sk-btn--danger control-confirm-yes"
                            disabled={busy}
                            onClick={() => void forget(fact)}
                          >
                            {busy
                              ? labels.forgetting
                              : labels.forgetYes(domain)}
                          </button>
                        </div>
                      </div>
                    ) : undefined
                  }
                />
              );
            })}
          </ul>
        </>
      )}
    </div>
  );
}

/** A recall that threw: no permission is calm text, anything else is the family's failure with Try again. */
function failedRecall(
  cause: unknown,
  labels: ControlLabels,
  retry: () => void,
) {
  if (writeFailure(cause) === "forbidden")
    return <p className="control-recall-line">{labels.recallForbidden}</p>;
  return (
    <ErrorNotice
      locale={labels.locale}
      message={labels.recallUnavailableHeading}
      cause={cause}
      onRetry={retry}
      placement="row"
    />
  );
}

/**
 * "Search memory": a free text question answered by recall_memory over every source the owner may read. The
 * results below it are mounted afresh for each search, so an older answer never stays under a newer question.
 */
export function MemorySearch({
  tools,
  labels,
  onForgotten,
  onModelContext,
}: {
  tools: RecallTools;
  labels: ControlLabels;
  onForgotten?: () => void;
  onModelContext?: (summary: string) => void;
}) {
  const inputId = useId();
  const [text, setText] = useState("");
  const [asked, setAsked] = useState<{ query: string; nonce: number } | null>(
    null,
  );
  const [tooShort, setTooShort] = useState(false);

  function submit() {
    const query = text.trim();
    if (query.length < 2) {
      setTooShort(true);
      return;
    }
    setTooShort(false);
    setAsked((current) => ({ query, nonce: (current?.nonce ?? 0) + 1 }));
  }

  return (
    <div className="control-search">
      <h3 className="control-section">
        <label htmlFor={inputId}>{labels.searchTitle}</label>
      </h3>
      <form
        role="search"
        className="control-search-form"
        onSubmit={preventSubmit}
      >
        <input
          id={inputId}
          type="search"
          className="sk-createfield__input"
          placeholder={labels.searchHint}
          maxLength={300}
          value={text}
          aria-invalid={tooShort || undefined}
          onChange={(event) => setText(event.target.value)}
          onKeyDown={(event) => onEnterKey(event, submit)}
        />
        <button type="button" className="sk-btn--secondary" onClick={submit}>
          {labels.searchButton}
        </button>
      </form>
      {tooShort ? (
        <p role="alert" className="control-notice control-notice-error">
          {labels.searchTooShort}
        </p>
      ) : null}
      {asked ? (
        <RecallResults
          key={`${asked.nonce}:${asked.query}`}
          request={{ query: asked.query }}
          tools={tools}
          labels={labels}
          onForgotten={onForgotten}
          onModelContext={onModelContext}
        />
      ) : null}
    </div>
  );
}
