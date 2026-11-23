import { useContext, useId, useRef, useState, type ReactNode } from "react";

import type { HostSettingsEntry, RoomTarget } from "../../mcp-apps/room-types";
import { ownerDayPlus } from "../../mcp-apps/ui/due";
import { MoreIcon } from "../../mcp-apps/ui/icons";
import { Menu, menuButtonKeys } from "../../mcp-apps/ui/menu";
import { ReceiptBar, useReceipt } from "../../mcp-apps/ui/receipt";
import { RoomSurfaceContext } from "../../mcp-apps/ui/room-context";
import { RoomHead } from "../../mcp-apps/ui/room-head";
import { MenuShortcutsRow } from "../../mcp-apps/ui/shortcut-help";
import { SplitAside } from "../../mcp-apps/ui/split-layout";
import { ErrorNotice, SkeletonRows } from "../../mcp-apps/ui/states";
import { HomeBlocks } from "./home-blocks";
import type { HomeLabels } from "./labels";
import { homeHeading, type StartHome } from "./model";
import { useReady } from "./ready";
import { useTaskDone } from "./use-task-done";
import type { HomeTransport } from "./transport";
import { useHome } from "./use-home";
import "../suggestions/suggestions.css";
import "./home.css";

/**
 * The Start room's home view: what needs the owner now, in the order of urgency (design §2.1.1), each block only when
 * get_start sent it. The day as the title and ⋯; then the insight sentence, the conversations ready to start, the way
 * to the suggestions with how many wait, today's tasks (at most three, "Öppna Agenda · n till ›"), what waits on
 * others, and the way to the automations with what they did since the owner last looked. A quiet day says so once.
 *
 * A ready conversation is started in the chat: "Starta" sends a phrase that names it (ui/message), and Claude starts
 * it with start_ready_conversation. Its instruction is never on this page and never a button; where the host has no
 * messages the phrase stands as text. "Hoppa över idag" skips it here, with Ångra in the receipt bar. A task of today
 * has the Agenda's ring: ticking it leaves the row, the count follows, and Ångra is in the receipt bar (use-task-done).
 *
 * In a wide frame the suggestion inbox (`aside`) stands beside the page, and the page then draws no row to it.
 */
export function StartHomeView({
  api,
  t,
  initial,
  refreshKey,
  onNavigate,
  sendMessage,
  control,
  suggestions,
  automations,
  aside,
}: {
  api: HomeTransport;
  t: HomeLabels;
  initial?: StartHome;
  refreshKey?: number;
  onNavigate?: (target: RoomTarget) => void;
  sendMessage?: (text: string) => Promise<boolean>;
  /** The last entry of ⋯: the memory and control entry, or the host's own settings. */
  control?: HostSettingsEntry;
  /** Where the suggestion inbox is, when the host can show it. */
  suggestions?: RoomTarget;
  /** Where the automations are, when the host can show them. */
  automations?: RoomTarget;
  /** What stands beside the page in a wide frame: the suggestion inbox. */
  aside?: ReactNode;
}) {
  const home = useHome(api, initial, refreshKey);
  const { read } = home;
  const receipt = useReceipt();
  const surface = useContext(RoomSurfaceContext);
  const inBar = Boolean(surface.headSlot);
  const besideInbox = Boolean(aside && surface.asideSlot);
  const titleRef = useRef<HTMLHeadingElement>(null);
  const ids = useId();

  const [moreOpen, setMoreOpen] = useState(false);
  const moreButton = useRef<HTMLButtonElement>(null);
  const panelId = `${ids}-more`;
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
          home.reload();
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
      {control ? (
        <button
          type="button"
          className="sk-menu-item"
          onClick={() => {
            close();
            control.onOpen();
          }}
        >
          {control.label}
        </button>
      ) : null}
    </Menu>
  );

  const ready = useReady({ api, t, receipt, reload: home.reload, titleRef });
  const done = useTaskDone({ api, t, receipt, reload: home.reload, titleRef });

  const day =
    read.phase === "ready" ? read.start.day : ownerDayPlus(new Date(), 0);

  let body: ReactNode;
  if (read.phase === "reading")
    body = (
      <div className="start-inbox-wait" aria-busy="true">
        <SkeletonRows rows={2} heading glyph={false} />
        <SkeletonRows rows={2} heading glyph={false} />
      </div>
    );
  else if (read.phase === "failed")
    body = (
      <ErrorNotice
        locale={t.dateLocale}
        subject="start:home"
        cause={read.cause}
        onRetry={home.retry}
      />
    );
  else
    body = (
      <HomeBlocks
        start={read.start}
        t={t}
        ready={ready}
        done={done}
        sendMessage={sendMessage}
        onNavigate={onNavigate}
        onRetry={home.reload}
        suggestions={besideInbox ? undefined : suggestions}
        automations={automations}
        stale={
          read.stale ? (
            <ErrorNotice
              locale={t.dateLocale}
              placement="refresh"
              subject="start:home"
              cause={read.stale.cause}
              onRetry={home.reload}
            />
          ) : null
        }
      />
    );

  return (
    <article className="sidekick-start start-home">
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
        <h2 className="start-inbox-title" ref={titleRef} tabIndex={-1}>
          {homeHeading(day, t.dateLocale)}
        </h2>
        {inBar ? null : moreButtonEl}
      </div>
      {inBar ? null : menu}
      {body}
      <ReceiptBar receipt={receipt} />
      {aside ? (
        <SplitAside>
          <RoomSurfaceContext.Provider
            value={{
              ...surface,
              headSlot: null,
              backActions: null,
              pane: undefined,
              asideSlot: null,
            }}
          >
            <div className="sidekick-start start-home-aside">{aside}</div>
          </RoomSurfaceContext.Provider>
        </SplitAside>
      ) : null}
    </article>
  );
}
