import { useCallback, useId, useState } from "react";

import { MessageBox } from "../../mcp-apps/ui/message-box";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { ErrorNotice, SkeletonRows } from "../../mcp-apps/ui/states";
import { useRead } from "../../mcp-apps/ui/use-read";
import { ApprovalCard } from "./approval";
import type { AutomationLabels } from "./labels";
import {
  capital,
  countsLine,
  factsOf,
  highlightText,
  momentText,
  reportOf,
  rowMeta,
  stateOf,
  type AutomationRecord,
  type AutomationReport,
} from "./model";
import type { AutomationTransport } from "./transport";
import "./automations.css";

/** An instruction longer than this is folded to its first lines, with "Visa allt". */
const LONG_INSTRUCTION = 320;

/**
 * One automation in full (the Start room's `automation` view; the detail beside the list in a wide frame): what it
 * does in the owner's words (its purpose), where it stands, the facts an approval binds (when, what it reads, what it
 * may propose, how suggestions are taken, its limits, who runs it, the model), the instruction itself, its runs since
 * the owner last looked (get_automation_report), and last the approval (ApprovalCard).
 */
export function AutomationDetailView({
  api,
  t,
  id,
  initial,
  refreshKey,
}: {
  api: AutomationTransport;
  t: AutomationLabels;
  id: string;
  initial?: AutomationRecord;
  refreshKey?: number;
}) {
  const read = useCallback(() => api.get(id), [api, id]);
  const [state, retry, replace] = useRead(read, refreshKey, initial);
  const receipt = useReceipt(id);
  // The approval was refused because the spec changed since it was shown: the new spec is read and the view says so.
  const [changed, setChanged] = useState(false);
  const reread = useCallback(() => {
    setChanged(true);
    read().then(replace, () => undefined);
  }, [read, replace]);

  if (state.phase === "reading")
    return (
      <div className="start-detail-wait" aria-busy="true">
        <SkeletonRows rows={4} heading glyph={false} />
      </div>
    );
  if (state.phase === "failed")
    return (
      <ErrorNotice
        locale={t.dateLocale}
        subject="start:automation"
        cause={state.cause}
        onRetry={retry}
      />
    );
  const record = state.value;
  return (
    <article className="sidekick-start start-automation">
      <AutomationBody record={record} t={t} />
      <RunsSection api={api} t={t} record={record} refreshKey={refreshKey} />
      {changed && record.approval !== "approved" ? (
        <MessageBox severity="info" title={t.changedWhileOpen} />
      ) : null}
      <ApprovalCard
        key={record.spec_digest}
        api={api}
        record={record}
        t={t}
        receipt={receipt}
        onApproved={replace}
        onChanged={reread}
      />
      <ReceiptBar receipt={receipt} />
    </article>
  );
}

function AutomationBody({
  record,
  t,
}: {
  record: AutomationRecord;
  t: AutomationLabels;
}) {
  const [whole, setWhole] = useState(false);
  const instructionId = useId();
  const long = record.instruction.length > LONG_INSTRUCTION;
  return (
    <>
      <header className="start-automation-head">
        <h2 className="start-automation-title">{record.title}</h2>
        <p className="start-automation-state" data-state={stateOf(record)}>
          {rowMeta(record, t)}
        </p>
      </header>
      <p className="start-automation-purpose">{record.purpose}</p>
      {stateOf(record) === "changed" ? (
        <MessageBox severity="warning" title={t.changedTitle}>
          {t.changedBody}
        </MessageBox>
      ) : null}
      <dl className="start-facts">
        {factsOf(record, t).map((fact) => (
          <div key={fact.key} className="start-fact">
            <dt>{fact.label}</dt>
            <dd>
              <span>{fact.value}</span>
              {fact.note ? (
                <span className="start-fact-note">{fact.note}</span>
              ) : null}
            </dd>
          </div>
        ))}
      </dl>
      <section
        className="start-automation-section"
        aria-labelledby={`${instructionId}-h`}
      >
        <h3
          className="start-automation-section-title"
          id={`${instructionId}-h`}
        >
          {t.instruction}
        </h3>
        <p
          id={instructionId}
          className="start-instruction"
          data-folded={long && !whole ? "true" : undefined}
        >
          {record.instruction}
        </p>
        {long ? (
          <button
            type="button"
            className="sk-more start-instruction-more"
            aria-expanded={whole}
            aria-controls={instructionId}
            onClick={() => setWhole((open) => !open)}
          >
            {whole ? t.showLess : t.showAll}
          </button>
        ) : null}
      </section>
    </>
  );
}

/** The runs since the owner last looked, from the report: one line of counts and at most three highlights. */
function RunsSection({
  api,
  t,
  record,
  refreshKey,
}: {
  api: AutomationTransport;
  t: AutomationLabels;
  record: AutomationRecord;
  refreshKey?: number;
}) {
  const headingId = useId();
  const [report, retry] = useRead<AutomationReport>(api.report, refreshKey);
  const lastRun = record.last_run_at
    ? t.lastRun(momentText(record.last_run_at, t.dateLocale))
    : t.neverRun;
  // "Senast körd mån 23 nov. 07:02 · räknat sedan fre 20 nov.": when it last ran, and where the counts start.
  const last = [
    capital(lastRun),
    report.phase === "ready" && api.report
      ? t.since(momentText(report.value.window.since, t.dateLocale, false))
      : undefined,
  ]
    .filter(Boolean)
    .join(" · ");
  let body;
  if (!api.report) body = null;
  else if (report.phase === "reading")
    body = <SkeletonRows rows={1} glyph={false} />;
  else if (report.phase === "failed")
    body = (
      <ErrorNotice
        locale={t.dateLocale}
        placement="row"
        message={t.reportFailed}
        onRetry={retry}
      />
    );
  else {
    const { counts, highlights } = reportOf(report.value, record.id);
    body = (
      <>
        <p className="start-runs-line">
          {counts && counts.runs > 0 ? countsLine(counts, t) : t.noRuns}
        </p>
        {highlights.length > 0 ? (
          <ul className="start-runs-highlights">
            {highlights.map((item, index) => (
              <li key={`${item.at}-${index}`} data-kind={item.kind}>
                <span>{highlightText(item, t)}</span>
                <span className="start-fact-note">
                  {momentText(item.at, t.dateLocale)}
                </span>
              </li>
            ))}
          </ul>
        ) : null}
      </>
    );
  }
  return (
    <section className="start-automation-section" aria-labelledby={headingId}>
      <h3 className="start-automation-section-title" id={headingId}>
        {t.runsHeading}
      </h3>
      <p className="sk-card__meta">{last}</p>
      {body}
    </section>
  );
}
