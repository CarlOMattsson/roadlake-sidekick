import { useId, type ReactNode } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import { Counted } from "../../mcp-apps/ui/count";
import { ChevronRightIcon } from "../../mcp-apps/ui/icons";
import { InsightLine } from "../../mcp-apps/ui/insight-line";
import { Row } from "../../mcp-apps/ui/row";
import { EmptyState, ErrorNotice } from "../../mcp-apps/ui/states";
import type { HomeLabels } from "./labels";
import {
  automationsMeta,
  failedParts,
  isQuiet,
  readyRows,
  recordTarget,
  suggestionsMeta,
  todayMeta,
  todayMore,
  waitingMeta,
  waitingMore,
  waitingTarget,
  type StartHome,
  type StartPart,
} from "./model";
import { ReadyCard, type ReadyState } from "./ready";

/** The page under its title: the blocks get_start sent, in their order, or the quiet day's one line. */
export function HomeBlocks({
  start,
  t,
  ready,
  sendMessage,
  onNavigate,
  onRetry,
  suggestions,
  automations,
  stale,
}: {
  start: StartHome;
  t: HomeLabels;
  ready: ReadyState;
  sendMessage?: (text: string) => Promise<boolean>;
  onNavigate?: (target: RoomTarget) => void;
  onRetry: () => void;
  suggestions?: RoomTarget;
  automations?: RoomTarget;
  stale: ReactNode;
}) {
  const ids = useId();
  const now = new Date();
  const failed = new Set(failedParts(start));
  const notice = (part: StartPart) =>
    failed.has(part) ? (
      <ErrorNotice
        locale={t.dateLocale}
        placement="row"
        message={t.unavailable[part]}
        onRetry={onRetry}
      />
    ) : null;
  const rows = readyRows(start, ready.hidden);
  const today = start.today;
  const waiting = start.waiting;
  const agenda: RoomTarget = { room: "work", view: "agenda" };
  const quiet = isQuiet(start, ready.hidden);

  const insight = start.insight?.text.trim() ? start.insight : undefined;
  const suggestionsLine = suggestionsMeta(start, t);
  const automationsLine = automationsMeta(start, t);

  return (
    <>
      {stale}
      {insight ? (
        <div className="start-home-insight">
          <InsightLine text={insight.text} locale={t.dateLocale} />
          {insight.written_by === "ai" ? (
            <p className="sk-card__meta start-home-ai">{t.aiWritten}</p>
          ) : null}
        </div>
      ) : null}
      {quiet ? (
        <EmptyState title={t.empty}>
          {onNavigate ? (
            <OpenButton
              label={t.openAgenda}
              onOpen={() => onNavigate(agenda)}
            />
          ) : null}
        </EmptyState>
      ) : null}

      {rows.length > 0 || failed.has("ready") ? (
        <section className="start-home-block" aria-labelledby={`${ids}-ready`}>
          <h3 className="start-inbox-section" id={`${ids}-ready`}>
            {t.readyHeading}
          </h3>
          {notice("ready")}
          {rows.length > 0 ? (
            <ul className="start-home-cards">
              {rows.map((row) => (
                <li key={row.id} className="start-home-card">
                  <ReadyCard
                    row={row}
                    t={t}
                    ready={ready}
                    sendMessage={sendMessage}
                  />
                </li>
              ))}
            </ul>
          ) : null}
        </section>
      ) : null}

      {suggestions && onNavigate ? (
        <div className="start-home-block">
          {notice("suggestions")}
          <ul className="start-home-links" aria-label={t.suggestions}>
            <Row
              primary={t.suggestions}
              secondary={
                suggestionsLine ? (
                  <span data-waiting="true">{suggestionsLine}</span>
                ) : undefined
              }
              navigates
              onOpen={() => onNavigate(suggestions)}
            />
          </ul>
        </div>
      ) : (
        notice("suggestions")
      )}

      {today?.items.length || failed.has("today") ? (
        <section className="start-home-block" aria-labelledby={`${ids}-today`}>
          <h3 className="start-inbox-section" id={`${ids}-today`}>
            {today ? (
              <Counted
                text={t.todayHeading(today.overdue_count + today.today_count)}
              />
            ) : (
              t.todayTitle
            )}
          </h3>
          {notice("today")}
          {today?.items.length ? (
            <>
              <ul className="start-home-rows">
                {today.items.map((row) => {
                  const meta = todayMeta(row, now, t);
                  const target = recordTarget(row);
                  return (
                    <Row
                      key={row.id}
                      primary={row.title}
                      secondary={
                        <span className="start-home-meta">
                          <span
                            data-tone={meta.overdue ? "overdue" : undefined}
                          >
                            {meta.due}
                          </span>
                          {meta.project ? ` · ${meta.project}` : null}
                        </span>
                      }
                      navigates={Boolean(target && onNavigate)}
                      onOpen={
                        target && onNavigate
                          ? () => onNavigate(target)
                          : undefined
                      }
                    />
                  );
                })}
              </ul>
              {onNavigate ? (
                <OpenButton
                  label={t.openAgenda}
                  more={
                    todayMore(today) > 0 ? t.more(todayMore(today)) : undefined
                  }
                  onOpen={() => onNavigate(agenda)}
                />
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {waiting?.items.length || failed.has("waiting") ? (
        <section
          className="start-home-block"
          aria-labelledby={`${ids}-waiting`}
        >
          <h3 className="start-inbox-section" id={`${ids}-waiting`}>
            {waiting ? (
              <Counted text={t.waitingHeading(waiting.total)} />
            ) : (
              t.waitingTitle
            )}
          </h3>
          {notice("waiting")}
          {waiting?.items.length ? (
            <>
              <ul className="start-home-rows">
                {waiting.items.map((row) => (
                  <Row
                    key={row.id}
                    primary={row.title}
                    secondary={
                      <span className="start-home-meta">
                        {waitingMeta(row, now, t)}
                      </span>
                    }
                    navigates={Boolean(onNavigate)}
                    onOpen={
                      onNavigate
                        ? () => onNavigate(waitingTarget(row))
                        : undefined
                    }
                  />
                ))}
              </ul>
              {waitingMore(waiting) > 0 ? (
                <p className="sk-card__meta start-home-more">
                  {t.waitingMore(waitingMore(waiting), waiting.capped)}
                </p>
              ) : null}
            </>
          ) : null}
        </section>
      ) : null}

      {automations && onNavigate ? (
        <div className="start-home-block">
          {notice("since_last")}
          <ul className="start-home-links" aria-label={t.automations}>
            <Row
              primary={t.automations}
              secondary={
                automationsLine ? (
                  <span
                    className="start-home-meta"
                    data-tone={automationsLine.failed ? "warning" : undefined}
                  >
                    {automationsLine.text}
                  </span>
                ) : undefined
              }
              navigates
              onOpen={() => onNavigate(automations)}
            />
          </ul>
        </div>
      ) : (
        notice("since_last")
      )}
    </>
  );
}

/** A list's way on in the full view: "Öppna Agenda · 1 till ›", a tertiary button on the rows' text edge. */
export function OpenButton({
  label,
  more,
  onOpen,
}: {
  label: string;
  more?: string;
  onOpen: () => void;
}) {
  return (
    <button
      type="button"
      className="sk-btn--open start-home-open"
      onClick={onOpen}
    >
      <span>
        {label}
        {more ? (
          <>
            {" "}
            <span className="start-home-open-more">{`· ${more}`}</span>
          </>
        ) : null}
      </span>
      <ChevronRightIcon />
    </button>
  );
}
