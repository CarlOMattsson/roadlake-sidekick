import { useCallback, useContext, useId, useRef, useState } from "react";

import type { RoomTarget } from "../../mcp-apps/room-types";
import { MoreIcon } from "../../mcp-apps/ui/icons";
import { Menu, menuButtonKeys } from "../../mcp-apps/ui/menu";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { RoomHead } from "../../mcp-apps/ui/room-head";
import { Row } from "../../mcp-apps/ui/row";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import {
  EmptyState,
  ErrorNotice,
  SkeletonRows,
} from "../../mcp-apps/ui/states";
import { useRead } from "../../mcp-apps/ui/use-read";
import type { AutomationLabels } from "./labels";
import {
  listOrder,
  rowMeta,
  stateOf,
  type AutomationPage,
  type AutomationSummary,
} from "./model";
import type { AutomationTransport } from "./transport";
import "./automations.css";

/** The target of one automation's detail. */
export function automationTarget(item: {
  id: string;
  title: string;
}): RoomTarget {
  return { room: "start", view: "automation", id: item.id, label: item.title };
}

/**
 * The automations (the Start room's `automations` view; a column beside the open automation in a wide frame): the
 * title "Automationer" and ⋯, then one row per automation, the ones that wait for the owner's approval first. A row's
 * line says where it stands ("Väntar på ditt godkännande", "På · senast körd …") and how many suggestions wait; it opens
 * the automation. A new `refreshKey` reads the list again in place.
 */
export function AutomationsList({
  api,
  t,
  initial,
  refreshKey,
  onOpen,
  sendMessage,
}: {
  api: AutomationTransport;
  t: AutomationLabels;
  initial?: AutomationPage;
  refreshKey?: number;
  onOpen?: (target: RoomTarget) => void;
  sendMessage?: (text: string) => Promise<boolean>;
}) {
  const [tick, setTick] = useState(0);
  const read = useCallback(() => api.list(), [api]);
  const [state, retry] = useRead(read, (refreshKey ?? 0) + tick, initial);
  const inBar = Boolean(useContext(RoomSurfaceContext).headSlot);

  const [moreOpen, setMoreOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  const panelId = useId();
  const close = () => setMoreOpen(false);
  const moreButtonEl = (
    <button
      ref={moreButton}
      type="button"
      className="sk-iconbtn sk-room-head__tool start-inbox-more-button"
      aria-label={t.moreActions}
      aria-expanded={moreOpen}
      aria-controls={panelId}
      onClick={() => setMoreOpen(!moreOpen)}
      onKeyDown={menuButtonKeys(moreOpen, setMoreOpen)}
    >
      <MoreIcon />
    </button>
  );
  const menu = (
    <Menu id={panelId} open={moreOpen} anchor={moreButton} onClose={close}>
      <button
        type="button"
        className="sk-menu-item"
        onClick={() => {
          close();
          setTick((value) => value + 1);
        }}
      >
        {t.refresh}
      </button>
      <MenuShortcutsRow
        onChosen={() => {
          close();
          moreButton.current?.focus();
        }}
      />
    </Menu>
  );

  let body;
  if (state.phase === "reading")
    body = (
      <div className="start-inbox-wait" aria-busy="true">
        <SkeletonRows rows={3} glyph={false} />
      </div>
    );
  else if (state.phase === "failed")
    body = (
      <ErrorNotice
        locale={t.dateLocale}
        subject="start:automations"
        cause={state.cause}
        onRetry={retry}
      />
    );
  else if (state.value.items.length === 0)
    body = (
      <EmptyState
        title={t.empty}
        hint={t.emptyHint}
        ask={{
          locale: t.dateLocale,
          example: t.emptyAsk,
          onSend: sendMessage
            ? () => void sendMessage(t.emptyAsk).catch(() => undefined)
            : undefined,
        }}
      />
    );
  else
    body = (
      <ul className="start-automation-rows" aria-label={t.title}>
        {listOrder(state.value.items).map((item) => (
          <AutomationRow key={item.id} item={item} t={t} onOpen={onOpen} />
        ))}
      </ul>
    );

  return (
    <article className="sidekick-start start-automations">
      {inBar ? (
        <RoomHead
          scope="sidekick-start"
          keysTitle={t.title}
          tabs={<span className="sk-shell-tabs-fill" aria-hidden="true" />}
          more={
            <>
              {moreButtonEl}
              {menu}
            </>
          }
        />
      ) : null}
      <div className="start-inbox-head">
        <h2 className="start-inbox-title">{t.title}</h2>
        {inBar ? null : moreButtonEl}
      </div>
      {inBar ? null : menu}
      {body}
    </article>
  );
}

function AutomationRow({
  item,
  t,
  onOpen,
}: {
  item: AutomationSummary;
  t: AutomationLabels;
  onOpen?: (target: RoomTarget) => void;
}) {
  const target = automationTarget(item);
  return (
    <Row
      primary={item.title}
      secondary={
        <span data-state={stateOf(item)} className="start-automation-meta">
          {rowMeta(item, t)}
        </span>
      }
      navigates={Boolean(onOpen)}
      onOpen={onOpen ? () => onOpen(target) : undefined}
      record={{ room: "start", view: "automation", id: item.id }}
    />
  );
}
